"""Israel adapter — data.gov.il (Israeli Companies Registrar / ICA).

Open data portal: https://data.gov.il/dataset/ica_companies
CKAN datastore API: https://data.gov.il/api/3/action/datastore_search

The dataset publishes the public register maintained by the Israel Corporations
Authority (Rasham Ha-Hevarot). For Israeli companies the 9-digit "Company
Number" doubles as the VAT registration number, so VAT lookups are routed
through the same field.

The datastore columns are Hebrew names *with spaces* (e.g. ``מספר חברה``,
``שם חברה``, ``שם באנגלית``) — filtering on an unknown column makes CKAN
return **409 Conflict** (ValidationError), which data.gov.il also uses when
rate-limiting. The adapter filters on the Hebrew column and keeps the legacy
English/underscore names as read-side fallbacks for older snapshots.

Listed-company financials live on TASE / Maya (https://maya.tase.co.il/) but
the disclosure portal does not expose a stable open JSON feed, so
`fetch_financials` returns an empty list for the MVP — the caller can still
follow `source_url` on `CompanyDetails`.
"""
from __future__ import annotations

import json
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

_COMPANY_NUMBER_RE = re.compile(r"^\d{9}$")

# CKAN resource id for the ICA companies dataset. The dataset slug
# (`ica_companies`) is stable but the underlying resource id occasionally
# rotates when the publisher republishes the file; override via env to avoid a
# code change in that case. Discover the current id via
# https://data.gov.il/api/3/action/package_show?id=ica_companies
# (verified current 2026-07-20).
_DEFAULT_RESOURCE_ID = "f004176c-b85f-4542-8901-7b3176f9a054"

_COMPANY_NUMBER_FIELD = "מספר חברה"


class _FilterRejected(AdapterError):
    """CKAN rejected the filter column name — dataset schema drift."""


def _normalize_company_number(value: str) -> str:
    cleaned = re.sub(r"[\s-]", "", value or "").strip()
    if not _COMPANY_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Israeli company number must be 9 digits, got: {value!r}"
        )
    return cleaned


class ILAdapter(CountryAdapter):
    country_code = "IL"
    country_name = "Israel"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://data.gov.il/api/3/action"

    def __init__(self, resource_id: str | None = None) -> None:
        self.resource_id = (
            resource_id
            or os.getenv("IL_ICA_RESOURCE_ID")
            or _DEFAULT_RESOURCE_ID
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(
                    client,
                    "/datastore_search",
                    params={"resource_id": self.resource_id, "limit": 1},
                )
                resp.raise_for_status()
                ok = bool(resp.json().get("success"))
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        if not ok:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes="data.gov.il CKAN returned success=false",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Financials via TASE/Maya not yet wired — listed cos only.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        records = await self._ckan_search(q=name, limit=limit)
        out: list[CompanyMatch] = []
        for rec in records[:limit]:
            cn = _record_company_number(rec)
            if not cn:
                continue
            out.append(
                CompanyMatch(
                    id=cn,
                    name=_record_name(rec),
                    country=self.country_code,
                    identifiers=_record_identifiers(rec, cn),
                    address=_record_address(rec),
                    status=_record_status(rec),
                    source_url=_source_url(cn),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"IL supports COMPANY_NUMBER or VAT, got {id_type}"
            )
        cn = _normalize_company_number(value)
        try:
            records = await self._ckan_search(
                filters={_COMPANY_NUMBER_FIELD: int(cn)}, limit=1
            )
        except _FilterRejected:
            records = []
        if not records:
            # Older snapshots published the column under English names — a
            # broad full-text `q` still hits those.
            records = await self._ckan_search(q=cn, limit=5)
            records = [r for r in records if _record_company_number(r) == cn]
            if not records:
                return None
        rec = records[0]
        return CompanyDetails(
            id=cn,
            name=_record_name(rec),
            country=self.country_code,
            legal_form=_first(
                rec, ["סוג תאגיד", "Company_Type", "company_type", "סוג_תאגיד"]
            ),
            status=_record_status(rec),
            incorporation_date=_parse_date(
                _first(
                    rec,
                    [
                        "תאריך התאגדות",
                        "Company_Registration_Date",
                        "company_registration_date",
                        "תאריך_התאגדות",
                    ],
                )
            ),
            registered_address=_record_address(rec),
            identifiers=_record_identifiers(rec, cn),
            raw=rec,
            source_url=_source_url(cn),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # TASE/Maya is the only free source of Israeli filings and it exposes
        # disclosures as HTML/PDF without a stable identifier-keyed JSON feed.
        # Leaving this empty keeps the "no mock data" rule intact; the UI can
        # still link to maya.tase.co.il via the company source_url.
        _normalize_company_number(company_id)
        return []

    async def _ckan_search(
        self,
        *,
        q: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "resource_id": self.resource_id,
            "limit": limit,
        }
        if q:
            params["q"] = q
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/datastore_search", params=params)
            if resp.status_code == 409:
                body = resp.text[:300]
                if filters and '"filters"' in body:
                    raise _FilterRejected(
                        f"data.gov.il rejected filter column "
                        f"{list(filters)} — dataset schema changed: {body}"
                    )
                raise AdapterError(
                    "data.gov.il returned 409 Conflict. Either the "
                    "ica_companies resource id rotated (discover the current "
                    "one via /api/3/action/package_show?id=ica_companies and "
                    "set IL_ICA_RESOURCE_ID) or the API is rate-limiting — "
                    f"back off and retry. Response: {body}"
                )
            resp.raise_for_status()
            payload = resp.json()
        if not payload.get("success"):
            return []
        return list((payload.get("result") or {}).get("records") or [])


def _first(rec: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        v = rec.get(k)
        if v not in (None, ""):
            return v
    return None


def _record_company_number(rec: dict[str, Any]) -> str | None:
    raw = _first(
        rec,
        [
            "מספר חברה",
            "Company_Number",
            "company_number",
            "מספר_חברה",
            "Company_ID",
        ],
    )
    if raw is None:
        return None
    cleaned = re.sub(r"[\s-]", "", str(raw))
    return cleaned if _COMPANY_NUMBER_RE.match(cleaned) else cleaned or None


def _record_name(rec: dict[str, Any]) -> str:
    name_en = _first(
        rec, ["שם באנגלית", "Company_Name_Eng", "company_name_eng", "Name_Eng"]
    )
    name_he = _first(rec, ["שם חברה", "Company_Name", "company_name", "שם_חברה"])
    if name_en and name_he and name_en != name_he:
        return f"{name_en} / {name_he}"
    return str(name_en or name_he or "")


def _record_status(rec: dict[str, Any]) -> str | None:
    status = _first(
        rec, ["סטטוס חברה", "Company_Status", "company_status", "סטטוס_חברה"]
    )
    return str(status) if status is not None else None


def _record_address(rec: dict[str, Any]) -> str | None:
    parts = [
        _first(rec, ["שם רחוב", "Company_Street", "company_street", "שם_רחוב"]),
        _first(
            rec,
            ["מספר בית", "Company_House_Number", "company_house_number", "מספר_בית"],
        ),
        _first(rec, ["שם עיר", "Company_City", "company_city", "שם_עיר"]),
        _first(rec, ["מיקוד", "Company_Zip", "company_zip"]),
    ]
    parts = [str(p) for p in parts if p not in (None, "")]
    return ", ".join(parts) or None


def _record_identifiers(
    rec: dict[str, Any], cn: str
) -> list[RegistryIdentifier]:
    # For Israeli companies the company number equals the VAT registration
    # number, so we surface both — downstream EU VIES-style flows expect a VAT
    # identifier on every record.
    return [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=cn,
            label="Company Number",
        ),
        RegistryIdentifier(
            type=IdentifierType.VAT,
            value=cn,
            label="VAT (Osek)",
        ),
    ]


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    text = str(s)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    # data.gov.il occasionally exposes dates as DD/MM/YYYY.
    try:
        d, m, y = text.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, IndexError):
        return None


def _source_url(cn: str) -> str:
    return f"https://data.gov.il/dataset/ica_companies?q={cn}"
