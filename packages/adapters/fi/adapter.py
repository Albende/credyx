"""Finland adapter — PRH Avoindata (Yritystietojärjestelmä YTJ).

Free, no auth: https://avoindata.prh.fi/opendata-ytj-api/v3/

Identifier: Y-tunnus (Business ID), 9 chars formatted as NNNNNNN-N.
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

_BID_RE = re.compile(r"^\d{7}-\d$")


class FIAdapter(CountryAdapter):
    country_code = "FI"
    country_name = "Finland"
    identifier_types = [IdentifierType.BUSINESS_ID]
    primary_identifier = IdentifierType.BUSINESS_ID
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(client, "/companies", params={"name": "Nokia", "pageSize": 1})
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
            notes="Financials require PRH paid service — not in MVP.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/companies", params={"name": name})
            resp.raise_for_status()
            data = resp.json()
        out: list[CompanyMatch] = []
        for c in (data.get("companies") or [])[:limit]:
            bid_field = c.get("businessId")
            bid = bid_field.get("value") if isinstance(bid_field, dict) else bid_field
            if not bid:
                continue
            name_val = _pick_name(c.get("names") or [])
            out.append(
                CompanyMatch(
                    id=bid,
                    name=name_val,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.BUSINESS_ID, value=bid, label="Y-tunnus"),
                    ],
                    address=_address(c.get("addresses") or []),
                    status=(c.get("status") or "active"),
                    source_url=f"https://tietopalvelu.ytj.fi/yritystiedot.aspx?ytunnus={bid}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.BUSINESS_ID:
            raise InvalidIdentifierError("FI only supports BUSINESS_ID")
        v = value.strip().replace(" ", "")
        if not _BID_RE.match(v):
            raise InvalidIdentifierError(f"Finnish Y-tunnus must look like 1234567-8: {value}")
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/companies", params={"businessId": v})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
        companies = payload.get("companies") or []
        if not companies:
            return None
        data = companies[0]
        return CompanyDetails(
            id=v,
            name=_pick_name(data.get("names") or []),
            country="FI",
            legal_form=(data.get("companyForms") or [{}])[0].get("type"),
            status=data.get("status"),
            incorporation_date=_parse_date(data.get("registrationDate")),
            registered_address=_address(data.get("addresses") or []),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.BUSINESS_ID, value=v, label="Y-tunnus"),
            ],
            raw=data,
            source_url=f"https://tietopalvelu.ytj.fi/yritystiedot.aspx?ytunnus={v}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        return []


def _pick_name(names: list[dict[str, Any]]) -> str:
    for n in names:
        if n.get("type") == "1" or n.get("language", "").lower() in {"fi", "en", "se"}:
            return n.get("name", "")
    return names[0].get("name", "") if names else ""


def _address(addresses: list[dict[str, Any]]) -> str | None:
    if not addresses:
        return None
    a = addresses[0]
    parts = [
        a.get("street"),
        a.get("buildingNumber"),
        a.get("postCode"),
        a.get("city"),
    ]
    parts = [str(p) for p in parts if p]
    return " ".join(parts) or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
