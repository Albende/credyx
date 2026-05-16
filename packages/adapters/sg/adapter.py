"""Singapore adapter — ACRA open data via data.gov.sg CKAN + SGX for listed firms.

Two free, no-auth sources are stitched together:

* **data.gov.sg CKAN datastore** — ACRA "Information on Corporate Entities"
  resources expose UEN, entity name, status, registration date, address,
  primary activity. The endpoint is the same across resources; the resource
  ID can be overridden via `SG_ACRA_RESOURCE_ID` (each entity class —
  local companies, foreign companies, LLPs, business names, etc. — has its
  own CKAN resource; the default targets "Information on Corporate Entities").
  No financials.
* **SGX (Singapore Exchange)** — `api.sgx.com` exposes free annual / quarterly
  company data for listed issuers, keyed by stock code. We probe the public
  search endpoint to resolve a UEN/name → SGX stock code, then pull annual
  reports. Unlisted Singapore companies have **no free financial source** —
  ACRA BizFile+ "Business Profile" downloads are paid (S$5.50/doc) and
  excluded from the MVP.

Identifier: **UEN** (Unique Entity Number), 9 or 10 alphanumeric chars.
Common formats (https://www.uen.gov.sg/ueninternet/faces/pages/aboutUEN.jspx):
  - `nnnnnnnnX`        — businesses registered before 2009 (9 chars)
  - `yyyynnnnnX`       — local companies (10 chars, year-prefixed)
  - `TyyPQnnnnX`       — entities issued by other agencies (10 chars,
    `T` + 2-digit year + 2-letter entity type + 4-digit serial + check letter,
    e.g. `T19LL1234A` for LLPs, `S12LL0001D` for societies).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
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

logger = logging.getLogger(__name__)

# UENs are 9 or 10 alphanumerics, uppercase. Validation is intentionally loose
# (no checksum) because ACRA does not publish the algorithm and several special
# prefixes exist (T, S, R, F …) — the registry itself is the source of truth.
_UEN_RE = re.compile(r"^[A-Z0-9]{9,10}$")


def _normalize_uen(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip()).upper()
    if not _UEN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Singapore UEN must be 9-10 alphanumeric characters: {value}"
        )
    return cleaned


class SGAdapter(CountryAdapter):
    country_code = "SG"
    country_name = "Singapore"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 60

    CKAN_BASE = "https://data.gov.sg/api/action"
    # Default ACRA resource — "Information on Corporate Entities". This can be
    # overridden at runtime if data.gov.sg republishes the dataset under a new
    # resource UUID; check https://data.gov.sg/datasets?topics=economy if the
    # default starts returning 404.
    DEFAULT_RESOURCE_ID = "eba1b8e0-ddbd-4e15-aedb-2c0a1c89c0a3"
    SGX_BASE = "https://api.sgx.com"
    BIZFILE_PROFILE_URL = "https://www.bizfile.gov.sg/ngbportal/CitizenSearch/{uen}"

    def __init__(self, resource_id: str | None = None) -> None:
        self.resource_id = (
            resource_id
            or os.getenv("SG_ACRA_RESOURCE_ID")
            or self.DEFAULT_RESOURCE_ID
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.CKAN_BASE) as client:
                resp = await get_with_retry(
                    client,
                    "/datastore_search",
                    params={"resource_id": self.resource_id, "limit": 1},
                )
                if resp.status_code == 404:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": False,
                        },
                        notes=(
                            "data.gov.sg resource not found — set "
                            "SG_ACRA_RESOURCE_ID to the current ACRA "
                            "Corporate Entities resource UUID."
                        ),
                    )
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("success"):
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": False,
                        },
                        notes="data.gov.sg returned success=false on probe.",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via ACRA open data ✅. Financials best-effort: "
                "SGX annual reports for listed issuers only; unlisted firms "
                "have no free source (BizFile+ profiles are paid)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._ckan_search(query=name.strip(), limit=limit)
        return [_row_to_match(r) for r in rows if _row_uen(r)]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Singapore only supports COMPANY_NUMBER (UEN), got {id_type}"
            )
        uen = _normalize_uen(value)
        rows = await self._ckan_search(query=uen, limit=25)
        match = _first_uen_match(rows, uen)
        if match is None:
            return None
        return _row_to_details(match)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        uen = _normalize_uen(company_id)

        # The name helps SGX resolve the issuer when the UEN isn't on its index.
        details = await self.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, uen)
        company_name = details.name if details else None

        stock_code = await self._resolve_sgx_stock_code(uen=uen, name=company_name)
        if not stock_code:
            return []

        return await self._fetch_sgx_annual(stock_code=stock_code, uen=uen, years=years)

    async def _ckan_search(self, *, query: str, limit: int) -> list[dict[str, Any]]:
        if not query:
            return []
        params = {
            "resource_id": self.resource_id,
            "q": query,
            "limit": str(max(1, min(limit, 100))),
        }
        async with build_http_client(base_url=self.CKAN_BASE) as client:
            resp = await get_with_retry(client, "/datastore_search", params=params)
            if resp.status_code == 404:
                raise AdapterError(
                    "data.gov.sg ACRA resource not found — set "
                    "SG_ACRA_RESOURCE_ID to a valid resource UUID."
                )
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                return []
        if not isinstance(payload, dict) or not payload.get("success"):
            return []
        result = payload.get("result") or {}
        records = result.get("records") or []
        return [r for r in records if isinstance(r, dict)]

    async def _resolve_sgx_stock_code(
        self, *, uen: str, name: str | None
    ) -> str | None:
        # SGX has no public UEN index; we match by exact UEN field if present in
        # the issuer record, else by name substring. Never invent — return None.
        query = name or uen
        if not query:
            return None
        try:
            async with build_http_client(base_url=self.SGX_BASE) as client:
                resp = await get_with_retry(
                    client,
                    "/securities/v1.1/securities",
                    params={"params": f"keyword={query}"},
                )
                if resp.status_code != 200:
                    return None
                try:
                    payload = resp.json()
                except ValueError:
                    return None
        except Exception as exc:
            logger.debug("SGX keyword lookup failed for %s: %s", query, exc)
            return None

        candidates = _extract_sgx_securities(payload)
        if not candidates:
            return None

        needle = (name or "").strip().lower()
        for c in candidates:
            sec_uen = (c.get("uen") or c.get("companyUEN") or "").strip().upper()
            if sec_uen and sec_uen == uen:
                code = c.get("nc") or c.get("code") or c.get("stockCode")
                if code:
                    return str(code).strip()
        if needle:
            for c in candidates:
                sec_name = (c.get("n") or c.get("name") or c.get("companyName") or "").lower()
                if sec_name and (needle in sec_name or sec_name in needle):
                    code = c.get("nc") or c.get("code") or c.get("stockCode")
                    if code:
                        return str(code).strip()
        return None

    async def _fetch_sgx_annual(
        self, *, stock_code: str, uen: str, years: int
    ) -> list[FinancialFiling]:
        filings: list[FinancialFiling] = []
        try:
            async with build_http_client(base_url=self.SGX_BASE) as client:
                resp = await get_with_retry(
                    client,
                    f"/securities/v1.1/issuers/{stock_code}/companyDataAnnual",
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                try:
                    payload = resp.json()
                except ValueError:
                    return []
        except Exception as exc:
            logger.debug(
                "SGX annual fetch failed for stock %s: %s", stock_code, exc
            )
            return []

        rows = _extract_sgx_annual_rows(payload)
        if not rows:
            return []
        from datetime import datetime as _dt

        cutoff_year = _dt.utcnow().year - years

        for row in rows:
            year_int = _coerce_int(
                row.get("year")
                or row.get("fiscalYear")
                or row.get("financialYear")
            )
            period_end = _parse_iso_date(
                row.get("periodEnd")
                or row.get("fiscalYearEnd")
                or row.get("endDate")
            )
            if year_int is None and period_end is not None:
                year_int = period_end.year
            if year_int is None:
                continue
            if year_int < cutoff_year:
                continue

            currency = (row.get("currency") or row.get("reportingCurrency") or "SGD").upper()
            document_url = (
                row.get("documentUrl")
                or row.get("annualReportUrl")
                or row.get("url")
            )
            structured = _structured_data_from_sgx(row)
            filings.append(
                FinancialFiling(
                    company_id=uen,
                    year=year_int,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency=currency,
                    structured_data=structured or None,
                    document_url=document_url,
                    document_format="json" if structured else (
                        "pdf" if document_url and document_url.lower().endswith(".pdf") else None
                    ),
                    source_url=(
                        f"https://www.sgx.com/securities/equities/{stock_code}"
                    ),
                )
            )
        filings.sort(key=lambda f: f.period_end or date.min, reverse=True)
        return filings


def _row_uen(row: dict[str, Any]) -> str | None:
    raw = (
        row.get("uen")
        or row.get("UEN")
        or row.get("uen_no")
        or row.get("unique_entity_number")
    )
    if raw is None:
        return None
    cleaned = str(raw).strip().upper()
    return cleaned or None


def _row_entity_name(row: dict[str, Any]) -> str:
    return str(
        row.get("entity_name")
        or row.get("name")
        or row.get("company_name")
        or ""
    ).strip()


def _row_status(row: dict[str, Any]) -> str | None:
    s = (
        row.get("entity_status_description")
        or row.get("entity_status")
        or row.get("uen_status")
        or row.get("status")
    )
    return str(s).strip() if s else None


def _row_address(row: dict[str, Any]) -> str | None:
    parts = [
        row.get("block"),
        row.get("street_name") or row.get("street"),
        row.get("level"),
        row.get("unit_no") or row.get("unit"),
        row.get("building_name") or row.get("building"),
        row.get("postal_code"),
    ]
    joined = " ".join(str(p).strip() for p in parts if p)
    if joined:
        return joined
    direct = row.get("registered_address") or row.get("address")
    if direct:
        return str(direct).strip()
    return None


def _row_to_match(row: dict[str, Any]) -> CompanyMatch:
    uen = _row_uen(row) or ""
    return CompanyMatch(
        id=uen,
        name=_row_entity_name(row),
        country="SG",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=uen, label="UEN"
            ),
        ],
        address=_row_address(row),
        status=_row_status(row),
        source_url=SGAdapter.BIZFILE_PROFILE_URL.format(uen=uen) if uen else None,
    )


def _row_to_details(row: dict[str, Any]) -> CompanyDetails:
    uen = _row_uen(row) or ""
    inc = _parse_iso_date(
        row.get("registration_incorporation_date")
        or row.get("registration_date")
        or row.get("incorporation_date")
    )
    diss = _parse_iso_date(
        row.get("ceased_date")
        or row.get("uen_issued_date_ended")
        or row.get("dissolution_date")
    )
    ssic = (
        row.get("primary_ssic_code")
        or row.get("ssic_code")
        or row.get("ssic")
    )
    sic_codes = [str(ssic)] if ssic else []
    return CompanyDetails(
        id=uen,
        name=_row_entity_name(row),
        country="SG",
        legal_form=(
            row.get("entity_type_description")
            or row.get("entity_type")
            or row.get("legal_form")
        ),
        status=_row_status(row),
        incorporation_date=inc,
        dissolution_date=diss,
        registered_address=_row_address(row),
        capital_amount=None,
        capital_currency="SGD",
        sic_codes=sic_codes,
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=uen, label="UEN"
            ),
        ],
        raw=row,
        source_url=SGAdapter.BIZFILE_PROFILE_URL.format(uen=uen) if uen else None,
    )


def _first_uen_match(
    rows: list[dict[str, Any]], uen: str
) -> dict[str, Any] | None:
    # CKAN `q=` returns full-text fuzzy hits; require an exact UEN match because
    # data.gov.sg sometimes serves multiple resources with overlapping fields.
    for r in rows:
        if (_row_uen(r) or "") == uen:
            return r
    return None


def _parse_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        # ACRA sometimes serves dates as DD/MM/YYYY.
        if len(s) >= 10 and s[2] == "/" and s[5] == "/":
            try:
                return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
            except ValueError:
                return None
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _extract_sgx_securities(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get("securities") or data.get("results")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    for key in ("securities", "results", "items"):
        v = payload.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _extract_sgx_annual_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "annualData", "items", "records"):
        v = payload.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            for inner_key in ("annual", "records", "rows"):
                inner = v.get(inner_key)
                if isinstance(inner, list):
                    return [x for x in inner if isinstance(x, dict)]
    return []


def _structured_data_from_sgx(row: dict[str, Any]) -> dict[str, Any]:
    # SGX issuer-data payloads vary; pick the canonical line items when present.
    # We surface only what's there — missing keys are skipped, never invented.
    mapping = {
        "revenue": ("revenue", "totalRevenue", "operatingRevenue"),
        "net_income": ("netIncome", "profitAfterTax", "netProfit"),
        "operating_income": ("operatingIncome", "operatingProfit", "ebit"),
        "total_assets": ("totalAssets",),
        "total_liabilities": ("totalLiabilities",),
        "total_equity": ("totalEquity", "shareholdersEquity"),
        "current_assets": ("currentAssets",),
        "current_liabilities": ("currentLiabilities",),
        "cash_and_equivalents": ("cashAndCashEquivalents", "cash"),
        "long_term_debt": ("longTermDebt", "nonCurrentBorrowings"),
        "short_term_debt": ("shortTermDebt", "currentBorrowings"),
    }
    out: dict[str, Any] = {}
    for canonical, candidates in mapping.items():
        for k in candidates:
            v = _coerce_float(row.get(k))
            if v is not None:
                out[canonical] = v
                break
    return out
