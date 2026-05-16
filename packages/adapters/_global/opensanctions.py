"""OpenSanctions API client for sanctions / PEP screening.

Free non-commercial API at https://api.opensanctions.org. Without an API key
the public endpoint is rate-limited to ~60 requests/minute; with a key
(`OPENSANCTIONS_API_KEY` env) the limit is roughly 600/min. For production
commercial use a license is required, but the free tier is fine for risk
flagging during dev/MVP.

Two surface methods:
- `screen()` calls POST /match/default with a single query and returns
  ranked `SanctionHit` candidates. Use this for credit screening — it is the
  scored matching endpoint OpenSanctions designs for KYC.
- `search()` is a thin wrapper around GET /search/default for free-text
  exploration; less precise but useful as a fallback.

Match scoring: returned `score` is OpenSanctions' confidence (Jaro-Winkler
plus structured features). Treat `>= 0.8` as a HIGH-confidence hit and
`0.6..0.8` as POSSIBLE. Callers decide what to do with each band.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from packages.adapters._base.http import build_http_client

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE_THRESHOLD = 0.8
POSSIBLE_MATCH_THRESHOLD = 0.6


class SanctionHit(BaseModel):
    """A single OpenSanctions match candidate."""

    model_config = ConfigDict(extra="ignore")

    id: str
    score: float = Field(ge=0.0, le=1.0)
    name: str
    schema_type: str
    datasets: list[str] = Field(default_factory=list)
    properties: dict[str, list[str]] = Field(default_factory=dict)
    source_url: str


class OpenSanctionsClient:
    BASE_URL = "https://api.opensanctions.org"
    ENTITY_URL_TEMPLATE = "https://www.opensanctions.org/entities/{id}/"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENSANCTIONS_API_KEY")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    async def screen(
        self,
        *,
        name: str,
        country: str | None = None,
        identifiers: list[str] | None = None,
        schema: str = "Company",
        limit: int = 5,
    ) -> list[SanctionHit]:
        """Screen a name against OpenSanctions and return ranked hits.

        Calls POST /match/default with a single-query batch. The schema
        controls which entity type is considered (Company, Person,
        Organization, LegalEntity, ...).

        Returns an empty list on network failure — sanctions screening must
        never block a credit decision. Callers should also surface this as a
        confidence drop when no hits are returned due to error vs. genuine
        absence.
        """
        name = name.strip()
        if not name:
            return []

        properties: dict[str, list[str]] = {"name": [name]}
        if country:
            properties["country"] = [country.lower()]
        if identifiers:
            cleaned = [i for i in (s.strip() for s in identifiers) if i]
            if cleaned:
                properties["registrationNumber"] = cleaned

        body = {
            "queries": {
                "q1": {
                    "schema": schema,
                    "properties": properties,
                }
            }
        }
        params = {"limit": limit}

        try:
            async with build_http_client(
                base_url=self.BASE_URL, headers=self._headers()
            ) as client:
                resp = await client.post("/match/default", json=body, params=params)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning("OpenSanctions unreachable for %r: %s", name, exc)
            return []

        if resp.status_code == 429:
            logger.warning(
                "OpenSanctions rate-limited (429) for %r; skipping", name
            )
            return []
        if resp.status_code >= 400:
            logger.warning(
                "OpenSanctions error %d for %r: %s",
                resp.status_code, name, resp.text[:200],
            )
            return []

        payload = resp.json() or {}
        responses = payload.get("responses") or {}
        q1 = responses.get("q1") or {}
        results = q1.get("results") or []

        hits: list[SanctionHit] = []
        for r in results:
            hit = self._coerce_hit(r)
            if hit is not None:
                hits.append(hit)
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    async def search(self, name: str, country: str | None = None) -> list[dict[str, Any]]:
        """Free-text search fallback. Kept for ad-hoc UI lookups."""
        params: dict[str, Any] = {"q": name, "limit": 5}
        if country:
            params["countries"] = country.lower()
        try:
            async with build_http_client(
                base_url=self.BASE_URL, headers=self._headers()
            ) as client:
                resp = await client.get("/search/default", params=params)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning("OpenSanctions search unreachable for %r: %s", name, exc)
            return []
        if resp.status_code >= 400:
            return []
        return resp.json().get("results", [])

    def _coerce_hit(self, raw: dict[str, Any]) -> SanctionHit | None:
        ent_id = raw.get("id")
        if not ent_id:
            return None
        score_raw = raw.get("score", raw.get("match_score", 0))
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))

        props = raw.get("properties") or {}
        name = raw.get("caption") or _first_prop(props, "name") or str(ent_id)
        schema_type = raw.get("schema") or "LegalEntity"
        datasets = raw.get("datasets") or []
        if not isinstance(datasets, list):
            datasets = [str(datasets)]

        cleaned_props: dict[str, list[str]] = {}
        for key, value in props.items():
            if isinstance(value, list):
                cleaned_props[str(key)] = [str(v) for v in value]
            else:
                cleaned_props[str(key)] = [str(value)]

        return SanctionHit(
            id=str(ent_id),
            score=score,
            name=str(name),
            schema_type=str(schema_type),
            datasets=[str(d) for d in datasets],
            properties=cleaned_props,
            source_url=self.ENTITY_URL_TEMPLATE.format(id=ent_id),
        )


async def screen_many(
    client: OpenSanctionsClient,
    targets: list[dict[str, Any]],
    *,
    max_concurrency: int = 5,
) -> list[list[SanctionHit]]:
    """Screen multiple entities in parallel, capped concurrency.

    Each target is a dict of kwargs forwarded to `client.screen()`. Results
    are returned in input order, one hit-list per target.
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(t: dict[str, Any]) -> list[SanctionHit]:
        async with sem:
            return await client.screen(**t)

    return await asyncio.gather(*(_one(t) for t in targets))


def _first_prop(props: dict[str, Any], key: str) -> str | None:
    val = props.get(key)
    if isinstance(val, list) and val:
        return str(val[0])
    if isinstance(val, str):
        return val
    return None
