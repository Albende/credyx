"""Israel adapter — data.gov.il (registry) + TASE/Maya (listed financials).

Registry (search + lookup): the Israel Corporations Authority (Rasham
Ha-Hevarot) public register, published as CKAN open data at
https://data.gov.il/dataset/ica_companies. The 9-digit "Company Number"
doubles as the VAT registration number, so VAT lookups route through the same
field. The datastore columns are Hebrew names *with spaces* (e.g. ``מספר חברה``,
``שם חברה``, ``שם באנגלית``); filtering on an unknown column makes CKAN return
**409 Conflict** (ValidationError), which data.gov.il also uses when
rate-limiting.

Financials (listed companies): the Tel Aviv Stock Exchange disclosure system
"Maya". Its two undocumented JSON hosts are read key-free:

- ``https://api.tase.co.il/api/content/searchentities`` — the full entity list
  (company short-name → Maya ``companyId``). Behind an Imperva WAF that only
  answers the legacy ``FSL`` user-agent it whitelists.
- ``https://mayaapi.tase.co.il/api/company/{alldetails,financereports}`` —
  per-company details (carries the 9-digit ``CorporateNo``, letting us verify a
  name match) and the latest filed financial reports. Answers any user-agent
  that sends the ``X-Maya-With: allow`` header.

The registrar company number is not present in the entity list, so
``fetch_financials`` resolves it by matching the registry name against Maya's
short names and then confirming the candidate's ``CorporateNo`` via
``alldetails`` before trusting the ``companyId``.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_COMPANY_NUMBER_RE = re.compile(r"^\d{9}$")

# CKAN resource id for the ICA companies dataset. The dataset slug
# (`ica_companies`) is stable but the underlying resource id occasionally
# rotates when the publisher republishes the file; override via env to avoid a
# code change in that case. Discover the current id via
# https://data.gov.il/api/3/action/package_show?id=ica_companies
# (verified current 2026-07-21).
_DEFAULT_RESOURCE_ID = "f004176c-b85f-4542-8901-7b3176f9a054"

_COMPANY_NUMBER_FIELD = "מספר חברה"

_TASE_API = "https://api.tase.co.il/api"
_MAYA_API = "https://mayaapi.tase.co.il/api"

# Imperva on api.tase.co.il only serves this legacy FSL user-agent; a modern
# browser UA is silently 403'd. mayaapi keys off the X-Maya-With header instead.
_TASE_HEADERS = {
    "User-Agent": "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; FSL 7.0.6.01001)",
    "Referer": "https://www.tase.co.il/",
    "Accept": "application/json, text/plain, */*",
}
_MAYA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "X-Maya-With": "allow",
    "Referer": "https://maya.tase.co.il/",
    "Accept": "application/json, text/plain, */*",
}

# Maya publishes the whole listed universe in one call, so it is cached in
# process rather than fetched per lookup.
_ENTITY_TYPE_COMPANY = 5
_ENTITIES_TTL_SECONDS = 6 * 3600
_entities_cache: dict[str, Any] = {"ts": 0.0, "companies": None}

_CURRENCY_BY_CODE = {1: "ILS", 2: "USD", 3: "EUR", 4: "GBP"}

_ANNUAL_MARKERS = ("שנתי", "annual", "10-k", "yearly")
_LEGAL_SUFFIX_RE = re.compile(
    r'\b(ltd\.?|limited|inc\.?|corp\.?|plc|b\.?m\.?|company)\b|בע["~\']?מ',
    re.IGNORECASE,
)


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
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Registry via data.gov.il; listed-company financials via TASE/Maya.",
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
        rec = await self._ckan_record(cn)
        if rec is None:
            return None
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
        cn = _normalize_company_number(company_id)
        rec = await self._ckan_record(cn)
        name_en = _first(
            rec or {}, ["שם באנגלית", "Company_Name_Eng", "company_name_eng", "Name_Eng"]
        )
        name_he = _first(rec or {}, ["שם חברה", "Company_Name", "company_name", "שם_חברה"])
        maya_id = await self._resolve_maya_company_id(cn, name_en, name_he)
        if maya_id is None:
            return []
        report = await self._maya_financereports(maya_id)
        if report is None:
            return []
        return self._build_filings(cn, maya_id, report, years)

    async def _ckan_record(self, cn: str) -> dict[str, Any] | None:
        try:
            records = await self._ckan_search(
                filters={_COMPANY_NUMBER_FIELD: int(cn)}, limit=1
            )
        except _FilterRejected:
            records = []
        if not records:
            records = await self._ckan_search(q=cn, limit=5)
            records = [r for r in records if _record_company_number(r) == cn]
        return records[0] if records else None

    async def _resolve_maya_company_id(
        self, company_number: str, name_en: Any, name_he: Any
    ) -> str | None:
        target_en = _normalize_name(name_en)
        target_he = _normalize_name(name_he)
        if not target_en and not target_he:
            return None
        companies = await self._load_maya_companies()
        scored: list[tuple[float, str]] = []
        for entity in companies:
            score = max(
                _name_score(entity.get("en"), target_en),
                _name_score(entity.get("he"), target_he),
            )
            if score > 0:
                scored.append((score, entity["id"]))
        scored.sort(reverse=True)
        for _, maya_id in scored[:12]:
            details = await self._maya_alldetails(maya_id)
            if details is None:
                continue
            corporate_no = re.sub(
                r"\D", "", str(details.get("CorporateNo") or "")
            )
            if corporate_no == company_number:
                return maya_id
        return None

    def _build_filings(
        self,
        company_number: str,
        maya_id: str,
        report: dict[str, Any],
        years: int,
    ) -> list[FinancialFiling]:
        currency = _CURRENCY_BY_CODE.get(report.get("CurrencyCode"))
        company_url = (
            f"https://maya.tase.co.il/en/company/{maya_id}?view=finance-reports"
        )
        candidates: list[tuple[int, FilingType, str, str | None]] = []

        previous_year = report.get("PreviousYear") or {}
        py_year = previous_year.get("Year")
        if isinstance(py_year, int):
            candidates.append(
                (py_year, FilingType.ANNUAL_REPORT, company_url, None)
            )

        for entry in report.get("LastReports") or []:
            title = str(entry.get("Title") or "")
            rpt_cd = entry.get("RptCd")
            year = _year_from_iso(entry.get("PubDate"))
            if year is None or rpt_cd is None:
                continue
            candidates.append(
                (
                    year,
                    _filing_type_from_title(title),
                    f"https://maya.tase.co.il/en/reports/{rpt_cd}",
                    date(year, 12, 31)
                    if _filing_type_from_title(title) is FilingType.ANNUAL_REPORT
                    else None,
                )
            )

        if not candidates:
            return []

        latest_year = max(year for year, *_ in candidates)
        min_year = latest_year - years + 1
        seen: set[tuple[int, FilingType, str]] = set()
        filings: list[FinancialFiling] = []
        for year, filing_type, source_url, period_end in sorted(
            candidates, key=lambda c: c[0], reverse=True
        ):
            if year < min_year:
                continue
            key = (year, filing_type, source_url)
            if key in seen:
                continue
            seen.add(key)
            filings.append(
                FinancialFiling(
                    company_id=company_number,
                    year=year,
                    type=filing_type,
                    period_end=period_end
                    or (date(year, 12, 31) if filing_type is FilingType.ANNUAL_REPORT else None),
                    currency=currency,
                    document_format="html",
                    source_url=source_url,
                )
            )
        return filings

    async def _load_maya_companies(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        cached = _entities_cache["companies"]
        if cached is not None and now - _entities_cache["ts"] < _ENTITIES_TTL_SECONDS:
            return cached
        english = await self._tase_searchentities(lang=1)
        hebrew = await self._tase_searchentities(lang=2)
        merged: dict[str, dict[str, Any]] = {}
        for lang_key, rows in (("en", english), ("he", hebrew)):
            for row in rows:
                if row.get("Type") != _ENTITY_TYPE_COMPANY:
                    continue
                cid = str(row.get("Id"))
                merged.setdefault(cid, {"id": cid, "en": None, "he": None})
                merged[cid][lang_key] = row.get("Name")
        companies = list(merged.values())
        _entities_cache["companies"] = companies
        _entities_cache["ts"] = now
        return companies

    async def _tase_searchentities(self, *, lang: int) -> list[dict[str, Any]]:
        async with build_http_client(
            base_url=_TASE_API, headers=_TASE_HEADERS
        ) as client:
            resp = await get_with_retry(
                client, "/content/searchentities", params={"lang": lang}
            )
            resp.raise_for_status()
            payload = resp.json()
        return payload if isinstance(payload, list) else []

    async def _maya_alldetails(self, company_id: str) -> dict[str, Any] | None:
        payload = await self._maya_get(
            "/company/alldetails", {"companyId": company_id, "lang": 1}
        )
        if not payload:
            return None
        return payload.get("CompanyDetails")

    async def _maya_financereports(self, company_id: str) -> dict[str, Any] | None:
        return await self._maya_get(
            "/company/financereports", {"companyId": company_id, "lang": 1}
        )

    async def _maya_get(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with build_http_client(
            base_url=_MAYA_API, headers=_MAYA_HEADERS
        ) as client:
            resp = await get_with_retry(client, path, params=params)
            if resp.status_code != 200:
                return None
            ctype = resp.headers.get("content-type", "").lower()
            if "json" not in ctype:
                return None
            payload = resp.json()
        return payload if isinstance(payload, dict) else None

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


def _normalize_name(value: Any) -> str:
    if not value:
        return ""
    text = _LEGAL_SUFFIX_RE.sub(" ", str(value))
    text = re.sub(r"[^0-9A-Za-z֐-׿]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().upper()


def _name_score(maya_name: Any, target: str) -> float:
    candidate = _normalize_name(maya_name)
    if not candidate or not target:
        return 0.0
    if candidate in target:
        return 0.5 + 0.5 * (len(candidate) / len(target))
    if target in candidate:
        return 0.5 + 0.5 * (len(target) / len(candidate))
    return SequenceMatcher(None, candidate, target).ratio()


def _filing_type_from_title(title: str) -> FilingType:
    lowered = title.lower()
    if any(marker in lowered for marker in _ANNUAL_MARKERS):
        return FilingType.ANNUAL_REPORT
    return FilingType.BALANCE_SHEET


def _year_from_iso(value: Any) -> int | None:
    if not value:
        return None
    match = re.match(r"(\d{4})", str(value))
    return int(match.group(1)) if match else None


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
