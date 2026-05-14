"""Norway adapter — Brønnøysundregistrene (Brreg).

Free open REST API: https://data.brreg.no/enhetsregisteret/api/
No auth, no rate limit documented (we throttle to 60/min anyway).

Identifier: organisasjonsnummer ("organisasjonsnummer"), 9 digits.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_ORG_RE = re.compile(r"^\d{9}$")


class NOAdapter(CountryAdapter):
    country_code = "NO"
    country_name = "Norway"
    identifier_types = [IdentifierType.ORG_NR]
    primary_identifier = IdentifierType.ORG_NR
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://data.brreg.no/enhetsregisteret/api"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(client, "/enheter", params={"navn": "equinor", "size": 1})
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code, name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            notes="Financials available via Regnskapsregisteret (PDFs) — not yet wired.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/enheter", params={"navn": name, "size": limit})
            resp.raise_for_status()
            data = resp.json()
        out: list[CompanyMatch] = []
        for e in (data.get("_embedded", {}) or {}).get("enheter", [])[:limit]:
            org = e.get("organisasjonsnummer")
            if not org:
                continue
            out.append(
                CompanyMatch(
                    id=org,
                    name=e.get("navn", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.ORG_NR, value=org, label="Org.nr"),
                    ],
                    address=_address(e.get("forretningsadresse") or {}),
                    status=("active" if not e.get("slettedato") else "ceased"),
                    source_url=f"https://w2.brreg.no/enhet/sok/detalj.jsp?orgnr={org}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.ORG_NR:
            raise InvalidIdentifierError("NO only supports ORG_NR")
        v = value.strip().replace(" ", "")
        if not _ORG_RE.match(v):
            raise InvalidIdentifierError(f"Norwegian org.nr must be 9 digits: {value}")
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, f"/enheter/{v}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        nace = data.get("naeringskode1") or {}
        return CompanyDetails(
            id=v,
            name=data.get("navn", ""),
            country="NO",
            legal_form=(data.get("organisasjonsform") or {}).get("kode"),
            status=("active" if not data.get("slettedato") else "ceased"),
            incorporation_date=_parse_date(data.get("registreringsdatoEnhetsregisteret")),
            dissolution_date=_parse_date(data.get("slettedato")),
            registered_address=_address(data.get("forretningsadresse") or {}),
            nace_codes=[nace["kode"]] if nace.get("kode") else [],
            identifiers=[
                RegistryIdentifier(type=IdentifierType.ORG_NR, value=v, label="Org.nr"),
            ],
            raw=data,
            source_url=f"https://w2.brreg.no/enhet/sok/detalj.jsp?orgnr={v}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Regnskapsregisteret distributes PDFs via a separate document service;
        # the document IDs require fetching the annual filings index. For MVP,
        # we leave this empty and point the UI at Brreg via source_url.
        return []


def _address(a: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if isinstance(a.get("adresse"), list):
        parts.extend(a["adresse"])
    elif a.get("adresse"):
        parts.append(a["adresse"])
    parts.append(str(a.get("postnummer", "")))
    parts.append(a.get("poststed", ""))
    parts = [p for p in parts if p]
    return ", ".join(parts) or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
