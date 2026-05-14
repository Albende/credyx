"""Netherlands adapter — KvK Handelsregister.

The KvK API requires an API key (test or production). The test environment is
free but rate-limited. Set env `NL_KVK_API_KEY` and optional `NL_KVK_BASE_URL`
to point to test vs prod.

Identifier: KvK number, 8 digits.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_KVK_RE = re.compile(r"^\d{8}$")


class NLAdapter(CountryAdapter):
    country_code = "NL"
    country_name = "Netherlands"
    identifier_types = [IdentifierType.KVK]
    primary_identifier = IdentifierType.KVK
    requires_api_key = True
    api_key_env = "NL_KVK_API_KEY"
    rate_limit_per_minute = 60

    DEFAULT_BASE_URL = "https://api.kvk.nl/api/v2"

    def __init__(self) -> None:
        self.api_key = os.getenv(self.api_key_env)
        self.base_url = os.getenv("NL_KVK_BASE_URL", self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key} if self.api_key else {}

    async def health_check(self) -> AdapterHealth:
        if not self.api_key:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True, api_key_present=False,
                notes=f"Set {self.api_key_env} to enable.",
            )
        try:
            async with build_http_client(base_url=self.base_url, headers=self._headers()) as client:
                resp = await get_with_retry(client, "/zoeken", params={"naam": "asml", "aantal": 1})
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True, api_key_present=True,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code, name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            requires_api_key=True, api_key_present=True,
            notes="Financials via deposited annual accounts (not free) — not yet wired.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with build_http_client(base_url=self.base_url, headers=self._headers()) as client:
            resp = await get_with_retry(client, "/zoeken", params={"naam": name, "aantal": limit})
            resp.raise_for_status()
            data = resp.json()
        out: list[CompanyMatch] = []
        for item in (data.get("resultaten") or [])[:limit]:
            kvk = item.get("kvkNummer")
            if not kvk:
                continue
            out.append(
                CompanyMatch(
                    id=kvk,
                    name=item.get("naam", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.KVK, value=kvk, label="KvK-nummer"),
                    ],
                    address=item.get("plaats"),
                    status=("active" if item.get("type") != "uitgeschreven" else "ceased"),
                    source_url=item.get("links", [{}])[0].get("href") if item.get("links") else None,
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.KVK:
            raise InvalidIdentifierError("NL only supports KVK")
        v = value.strip().replace(" ", "")
        if not _KVK_RE.match(v):
            raise InvalidIdentifierError(f"Dutch KvK number must be 8 digits: {value}")
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with build_http_client(base_url=self.base_url, headers=self._headers()) as client:
            resp = await get_with_retry(client, f"/basisprofielen/{v}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        return CompanyDetails(
            id=v,
            name=data.get("handelsnamen", [{}])[0].get("naam", "") if data.get("handelsnamen") else data.get("naam", ""),
            country="NL",
            legal_form=(data.get("_embedded", {}).get("eigenaar", {}) or {}).get("rechtsvorm"),
            status=data.get("indicatieIngeschreven") and "active" or "ceased",
            incorporation_date=_parse_date(data.get("formeleRegistratiedatum")),
            registered_address=_address(data.get("_embedded", {})),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.KVK, value=v, label="KvK-nummer"),
            ],
            raw=data,
            source_url=f"https://www.kvk.nl/zoeken/?source=all&q={v}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        return []


def _address(embedded: dict[str, Any]) -> str | None:
    eig = embedded.get("eigenaar") or {}
    adr = (eig.get("bezoekadres") or {})
    parts = [adr.get("straatnaam"), adr.get("huisnummer"), adr.get("postcode"), adr.get("plaats")]
    parts = [str(p) for p in parts if p]
    return " ".join(parts) or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
