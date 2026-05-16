"""Ireland adapter — CRO (Companies Registration Office) CWS API.

Endpoint base: https://services.cro.ie/cws/

The CRO Web Services (CWS) API exposes JSON over HTTP for:
- /cws/companies?company_name=...        (name search)
- /cws/company/{company_num}/{ind}       (single-company detail; ind = C|B)
- /cws/company/{company_num}/{ind}/submissions
                                          (filing history; documents are paid)
- /cws/status                             (health probe; no auth)

Auth: HTTP Basic. Credentials are free upon registration with the CRO but
are not anonymous — the live endpoints respond 401 without them. We treat
them like an API key: env vars IE_CRO_API_USERNAME / IE_CRO_API_PASSWORD.

Identifier: CRO Company Number, 1–7 digits (numeric). The "company_bus_ind"
selector defaults to "C" (company); business names use "B" but the credit
use-case here is companies only.

Documents (annual returns / B1 forms) cost €2.50 each through CRO; we return
metadata + the CRO download URL only — no PDF retrieval, no mock content.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

import httpx

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

_CRO_NUM_RE = re.compile(r"^\d{1,7}$")
_IE_VAT_RE = re.compile(r"^IE?\d{7}[A-Z]{1,2}$", re.IGNORECASE)


def _normalize_cro_number(value: str) -> str:
    cleaned = value.strip().replace(" ", "").lstrip("0")
    if not cleaned:
        cleaned = "0"
    if not _CRO_NUM_RE.match(cleaned):
        raise InvalidIdentifierError(f"IE CRO number invalid: {value}")
    return cleaned


class IEAdapter(CountryAdapter):
    country_code = "IE"
    country_name = "Ireland"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = "IE_CRO_API_USERNAME"
    rate_limit_per_minute = 60

    BASE_URL = "https://services.cro.ie/cws"
    PUBLIC_PORTAL = "https://search.cro.ie"

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.username = username or os.getenv("IE_CRO_API_USERNAME")
        self.password = password or os.getenv("IE_CRO_API_PASSWORD")

    def _auth(self) -> httpx.BasicAuth | None:
        if not self.username or not self.password:
            return None
        return httpx.BasicAuth(self.username, self.password)

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            auth=self._auth(),
            headers={"Accept": "application/json"},
        )

    async def health_check(self) -> AdapterHealth:
        creds_present = bool(self.username and self.password)
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(client, "/status")
                resp.raise_for_status()
                service_up = b"true" in resp.content.lower() or b"running" in resp.content.lower()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=creds_present,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        if not service_up:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=creds_present,
                notes="CRO /status reported services not running.",
            )
        if not creds_present:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Set IE_CRO_API_USERNAME and IE_CRO_API_PASSWORD to enable.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Filing PDFs are paid (€2.50 / doc) — metadata only returned.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        self._require_credentials()
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                "/companies",
                params={
                    "company_name": name,
                    "company_bus_ind": "C",
                    "searchType": "3",
                    "max": str(limit),
                    "htmlEnc": "1",
                },
            )
            resp.raise_for_status()
            payload = _safe_json(resp)

        items = _as_list(payload)
        matches: list[CompanyMatch] = []
        for item in items[:limit]:
            cro_num = _str(item, "company_num")
            if not cro_num:
                continue
            cro_norm = _normalize_cro_number(cro_num)
            matches.append(
                CompanyMatch(
                    id=cro_norm,
                    name=_str(item, "company_name") or "",
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=cro_norm,
                            label="CRO Number",
                        )
                    ],
                    address=_address_from_search(item),
                    status=_str(item, "company_status_desc")
                    or _str(item, "company_status"),
                    source_url=f"{self.PUBLIC_PORTAL}/company/CompanyDetails.aspx?id={cro_norm}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            v = value.strip().replace(" ", "")
            if not _IE_VAT_RE.match(v):
                raise InvalidIdentifierError(f"IE VAT invalid: {value}")
            raise InvalidIdentifierError(
                "CRO is not indexed by VAT; use COMPANY_NUMBER. "
                "For Irish VAT validation use the EU VIES adapter."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"IE supports COMPANY_NUMBER (and rejects VAT for lookup), got {id_type}"
            )
        cro_num = _normalize_cro_number(value)
        self._require_credentials()

        async with self._client() as client:
            resp = await get_with_retry(
                client,
                f"/company/{cro_num}/C",
                params={"htmlEnc": "1"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = _safe_json(resp)

        record = data[0] if isinstance(data, list) and data else data
        if not isinstance(record, dict):
            return None
        if not _str(record, "company_num") and not _str(record, "company_name"):
            # CRO returns a Company with null values when the number is invalid.
            return None
        return _details_from_company(record, cro_num)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        self._require_credentials()
        cro_num = _normalize_cro_number(company_id)
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                f"/company/{cro_num}/C/submissions",
                params={"htmlEnc": "1"},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = _safe_json(resp)

        items = _as_list(payload)
        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        for item in items:
            sub_type = (
                _str(item, "submission_type")
                or _str(item, "sub_type_desc")
                or _str(item, "doc_type_desc")
                or ""
            ).upper()
            if not _is_financial_filing(sub_type):
                continue
            period = (
                _parse_date(_str(item, "effective_date"))
                or _parse_date(_str(item, "received_date"))
                or _parse_date(_str(item, "submission_date"))
            )
            if not period or period.year < cutoff_year:
                continue
            sub_num = _str(item, "submission_num") or _str(item, "sub_num")
            doc_num = _str(item, "doc_num") or _str(item, "document_num")
            document_url = None
            if sub_num and doc_num:
                document_url = (
                    f"{IEAdapter.BASE_URL}/submission/{sub_num}/{doc_num}"
                )
            filings.append(
                FinancialFiling(
                    company_id=cro_num,
                    year=period.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period,
                    currency="EUR",
                    structured_data=None,
                    document_url=document_url,
                    document_format="pdf",
                    source_url=(
                        f"{IEAdapter.PUBLIC_PORTAL}/company/CompanySubmissions.aspx"
                        f"?id={cro_num}"
                    ),
                )
            )
        return filings

    def _require_credentials(self) -> None:
        if not self.username or not self.password:
            raise AdapterError(
                "Missing CRO credentials: set IE_CRO_API_USERNAME and IE_CRO_API_PASSWORD."
            )


def _safe_json(resp: httpx.Response) -> Any:
    # CRO returns text/xml on some errors even when JSON is requested; tolerate that.
    try:
        return resp.json()
    except ValueError:
        return None


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("companies", "results", "items", "submissions"):
            v = payload.get(key)
            if isinstance(v, list):
                return [p for p in v if isinstance(p, dict)]
        return [payload]
    return []


def _str(d: dict[str, Any], key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _address_from_search(item: dict[str, Any]) -> str | None:
    parts = [
        _str(item, "company_addr_1"),
        _str(item, "company_addr_2"),
        _str(item, "company_addr_3"),
        _str(item, "company_addr_4"),
        _str(item, "eircode"),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    s = value.strip()
    # CRO uses ISO dates and sometimes Microsoft \/Date(ms)\/ wrappers.
    if s.startswith("/Date(") and s.endswith(")/"):
        try:
            ms = int(s[6:-2].split("+")[0].split("-")[0])
            return datetime.utcfromtimestamp(ms / 1000).date()
        except (ValueError, TypeError):
            return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _is_financial_filing(sub_type: str) -> bool:
    if not sub_type:
        return False
    needle = sub_type.upper()
    return (
        "B1" in needle
        or "ANNUAL RETURN" in needle
        or "ACCOUNTS" in needle
        or "FINANCIAL" in needle
    )


def _details_from_company(record: dict[str, Any], cro_num: str) -> CompanyDetails:
    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=cro_num,
            label="CRO Number",
        )
    ]
    vat = _str(record, "vat_number") or _str(record, "vat")
    if vat and _IE_VAT_RE.match(vat.replace(" ", "")):
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=vat.upper().replace(" ", ""),
                label="Irish VAT",
            )
        )

    addr = ", ".join(
        p for p in [
            _str(record, "company_addr_1"),
            _str(record, "company_addr_2"),
            _str(record, "company_addr_3"),
            _str(record, "company_addr_4"),
            _str(record, "eircode"),
        ] if p
    ) or None

    return CompanyDetails(
        id=cro_num,
        name=_str(record, "company_name") or "",
        country="IE",
        legal_form=_str(record, "company_type_desc") or _str(record, "company_type"),
        status=_str(record, "company_status_desc") or _str(record, "company_status"),
        incorporation_date=_parse_date(_str(record, "company_reg_date")),
        dissolution_date=_parse_date(_str(record, "company_dissolved_date")),
        registered_address=addr,
        capital_amount=None,
        capital_currency="EUR",
        identifiers=identifiers,
        raw=record,
        source_url=f"{IEAdapter.PUBLIC_PORTAL}/company/CompanyDetails.aspx?id={cro_num}",
    )
