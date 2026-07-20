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
    FilingType,
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
    XBRL_URL = "https://avoindata.prh.fi/opendata-xbrl-api/v3"

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
            capabilities={"search": True, "lookup": True, "financials": True},
            notes="Financials via PRH Opendata XBRL API (iXBRL digital statements only, ~5% of filers).",
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
            out.append(
                CompanyMatch(
                    id=bid,
                    name=_pick_name(c.get("names") or []),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.BUSINESS_ID, value=bid, label="Y-tunnus"),
                    ],
                    address=_address(c.get("addresses") or []),
                    status=_status(c),
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
        line = data.get("mainBusinessLine") or {}
        return CompanyDetails(
            id=v,
            name=_pick_name(data.get("names") or []),
            country="FI",
            legal_form=_legal_form(data.get("companyForms") or []),
            status=_status(data),
            incorporation_date=_parse_date(data.get("registrationDate")),
            registered_address=_address(data.get("addresses") or []),
            nace_codes=[str(line["type"])] if line.get("type") else [],
            website=(data.get("website") or {}).get("url") if isinstance(data.get("website"), dict) else data.get("website"),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.BUSINESS_ID, value=v, label="Y-tunnus"),
            ],
            raw=data,
            source_url=f"https://tietopalvelu.ytj.fi/yritystiedot.aspx?ytunnus={v}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        v = company_id.strip().replace(" ", "")
        if not _BID_RE.match(v):
            raise InvalidIdentifierError(f"Finnish Y-tunnus must look like 1234567-8: {company_id}")
        async with build_http_client(base_url=self.XBRL_URL) as client:
            resp = await get_with_retry(client, "/financials", params={"businessId": v})
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        periods = payload.get("financials") or []
        periods.sort(key=lambda p: p.get("financialDate") or "", reverse=True)
        out: list[FinancialFiling] = []
        for p in periods[:years]:
            end = _parse_date(p.get("financialDate"))
            if end is None:
                continue
            out.append(
                FinancialFiling(
                    company_id=v,
                    year=end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=end,
                    currency="EUR",
                    document_url=(
                        f"{self.XBRL_URL}/financial?businessId={v}"
                        f"&financialDate={end.isoformat()}"
                    ),
                    document_format="xbrl",
                    source_url=f"https://tietopalvelu.ytj.fi/yritystiedot.aspx?ytunnus={v}",
                )
            )
        return out


def _desc(descriptions: list[dict[str, Any]], preferred: str = "3") -> str | None:
    by_lang = {d.get("languageCode"): d.get("description") for d in descriptions}
    return by_lang.get(preferred) or by_lang.get("1") or (
        descriptions[0].get("description") if descriptions else None
    )


def _pick_name(names: list[dict[str, Any]]) -> str:
    current = [n for n in names if n.get("type") == "1" and not n.get("endDate")]
    if current:
        return current[0].get("name", "")
    primary = [n for n in names if n.get("type") == "1"]
    if primary:
        return primary[0].get("name", "")
    return names[0].get("name", "") if names else ""


def _address(addresses: list[dict[str, Any]]) -> str | None:
    if not addresses:
        return None
    a = addresses[0]
    offices = a.get("postOffices") or []
    city = None
    for o in offices:
        if o.get("languageCode") == "1":
            city = o.get("city")
            break
    if city is None and offices:
        city = offices[0].get("city")
    parts = [
        a.get("street"),
        a.get("buildingNumber"),
        a.get("postCode"),
        city,
    ]
    parts = [str(p) for p in parts if p]
    return " ".join(parts) or None


def _legal_form(forms: list[dict[str, Any]]) -> str | None:
    current = [f for f in forms if not f.get("endDate")] or forms
    if not current:
        return None
    return _desc(current[0].get("descriptions") or [])


def _status(company: dict[str, Any]) -> str | None:
    situations = company.get("companySituations") or []
    flags = [_desc(s.get("descriptions") or []) for s in situations]
    flags = [f for f in flags if f]
    if flags:
        return "; ".join(flags)
    for entry in company.get("registeredEntries") or []:
        if entry.get("register") == "4" and not entry.get("endDate"):
            return _desc(entry.get("descriptions") or [])
    return "Registered" if company.get("tradeRegisterStatus") == "1" else None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
