"""Nigeria adapter — CAC iCRP public search + NGX financial statements.

Source coverage (all free, no API key):

* **CAC iCRP** (Corporate Affairs Commission, "CRP 3.0"). The public search
  SPA at https://icrp.cac.gov.ng/public-search is backed by a public JSON
  API: ``POST https://authapp.cac.gov.ng/name_similarity_app/api/public_search/search``
  with ``{"searchTerm": ..., "SearchType": "ALL"}``. It returns the approved
  name, RC number, registration date, classification, nature of business and
  status for every registered company / business name. Used for both
  ``search_by_name`` and ``lookup_by_identifier(COMPANY_NUMBER, rc)``.
* **NGX** (Nigerian Exchange). The corporate-disclosures backend is a
  SharePoint list ``XFinancial_News`` served by an anonymous OData endpoint at
  ``https://doclib.ngxgroup.com/_api/Web/Lists/GetByTitle('XFinancial_News')/items``.
  Filtering by ``Type_of_Submission eq 'Financial Statements'`` and the issuer
  name yields the filed quarterly + audited annual financial statements, each
  with a directly downloadable PDF on ``doclib.ngxgroup.com``. Unlisted
  companies have no NGX filings, so ``fetch_financials`` returns ``[]`` for
  them (a real factual answer — matches the FR / MA convention).

Identifiers:
- COMPANY_NUMBER → RC number (Registration of Companies), e.g. `RC208767`
  or `208767`. Normalised by stripping the `RC` prefix and spaces.
- VAT → TIN (Tax Identification Number). No free public TIN→company resolver
  exists today, so that path raises `AdapterNotImplementedError`.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client
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

_RC_RE = re.compile(r"^\d{1,10}$")
_TIN_RE = re.compile(r"^\d{8,14}$")
_LEGAL_SUFFIXES = ("PLC", "LIMITED", "LTD", "INCORPORATED", "INC")


def _normalize_rc(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip().upper())
    if cleaned.startswith("RC"):
        cleaned = cleaned[2:]
    cleaned = cleaned.lstrip("-/ ")
    if not _RC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Nigeria RC must be 1–10 digits (optionally RC-prefixed), got: {value}"
        )
    return cleaned


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Nigeria TIN must be 8–14 digits, got: {value}"
        )
    return cleaned


def _clean_rc(raw: str) -> str:
    """Reduce a CAC ``rcNumber`` field to a bare comparison key.

    CAC returns the value inconsistently — ``208767``, ``RC 613``, ``KD023538``.
    Strip a leading ``RC`` and all whitespace so equal companies compare equal.
    """
    cleaned = re.sub(r"\s+", "", (raw or "").strip().upper())
    if cleaned.startswith("RC"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("-/")


class NGAdapter(CountryAdapter):
    country_code = "NG"
    country_name = "Nigeria"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CAC_SEARCH_API = (
        "https://authapp.cac.gov.ng/name_similarity_app/api/public_search/search"
    )
    CAC_PUBLIC_URL = "https://icrp.cac.gov.ng/public-search"
    NGX_LIST_API = (
        "https://doclib.ngxgroup.com/_api/Web/Lists/"
        "GetByTitle('XFinancial_News')/items"
    )
    NGX_DISCLOSURES_URL = "https://ngxgroup.com/exchange/data/corporate-disclosures/"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Coverage: CAC iCRP public JSON search (name + RC); NGX XFinancial_News "
            "financial statements (downloadable PDFs) for listed issuers."
        )
        capabilities = {"search": True, "lookup": True, "financials": True}
        try:
            async with build_http_client(timeout=15.0) as client:
                rows = await self._cac_search(client, "dangote cement", limit=1)
            if not rows:
                return AdapterHealth(
                    country_code=self.country_code,
                    name=self.country_name,
                    status=AdapterStatus.DEGRADED,
                    capabilities=capabilities,
                    requires_api_key=False,
                    api_key_present=True,
                    rate_limit_per_minute=self.rate_limit_per_minute,
                    notes=f"CAC search returned no rows on probe. {notes}",
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"CAC probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities=capabilities,
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def _cac_search(
        self, client: httpx.AsyncClient, term: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        resp = await client.post(
            self.CAC_SEARCH_API,
            json={"searchTerm": term, "SearchType": "ALL"},
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://icrp.cac.gov.ng",
                "Referer": "https://icrp.cac.gov.ng/",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") or []
        return rows[:limit] if limit else rows

    def _match_from_row(self, row: dict[str, Any]) -> CompanyMatch:
        rc = _clean_rc(str(row.get("rcNumber") or ""))
        return CompanyMatch(
            id=rc or str(row.get("companyId") or ""),
            name=str(row.get("approvedName") or "").strip(),
            country="NG",
            status=row.get("status"),
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=rc,
                    label="RC Number",
                )
            ]
            if rc
            else [],
            source_url=self.CAC_PUBLIC_URL,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if len(query) < 2:
            raise InvalidIdentifierError(
                "Nigeria CAC name search requires at least 2 characters."
            )
        try:
            async with build_http_client(timeout=25.0) as client:
                rows = await self._cac_search(client, query, limit=limit)
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"CAC iCRP search unreachable ({exc.__class__.__name__})."
            ) from exc

        matches = [
            self._match_from_row(r) for r in rows if (r.get("approvedName") or "").strip()
        ]
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            rc = _normalize_rc(value)
            return await self._lookup_by_rc(rc)
        if id_type == IdentifierType.VAT:
            _normalize_tin(value)
            raise AdapterNotImplementedError(
                "Nigeria has no free public TIN→company resolver. The FIRS/JTB TIN "
                "verification portal is session-gated; the CAC tax-id endpoint runs "
                "RC→TIN only. Use COMPANY_NUMBER (RC) for lookups."
            )
        raise InvalidIdentifierError(
            f"Nigeria adapter only supports COMPANY_NUMBER (RC) or VAT (TIN), got {id_type}"
        )

    async def _lookup_by_rc(self, rc: str) -> CompanyDetails | None:
        try:
            async with build_http_client(timeout=25.0) as client:
                rows = await self._cac_search(client, rc, limit=50)
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"CAC iCRP RC lookup unreachable ({exc.__class__.__name__})."
            ) from exc

        row = next((r for r in rows if _clean_rc(str(r.get("rcNumber") or "")) == rc), None)
        if row is None:
            return None

        return CompanyDetails(
            id=rc,
            name=str(row.get("approvedName") or "").strip(),
            country="NG",
            legal_form=row.get("classificationName"),
            status=row.get("status"),
            incorporation_date=_parse_date(row.get("companyRegistrationDate")),
            registered_address=None,
            capital_amount=None,
            capital_currency="NGN",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=rc,
                    label="RC Number",
                ),
            ],
            raw={
                "source": "authapp.cac.gov.ng/name_similarity_app",
                "companyId": row.get("companyId"),
                "classificationId": row.get("classificationId"),
                "natureOfBusiness": (row.get("natureOfBusiness") or "").strip() or None,
                "rcNumberRaw": row.get("rcNumber"),
            },
            source_url=self.CAC_PUBLIC_URL,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        rc = _normalize_rc(company_id)

        async with build_http_client(timeout=30.0) as client:
            rows = await self._cac_search(client, rc, limit=50)
            row = next(
                (r for r in rows if _clean_rc(str(r.get("rcNumber") or "")) == rc), None
            )
            if row is None:
                return []
            core = _core_name(str(row.get("approvedName") or ""))
            if not core:
                return []
            filings = await self._ngx_financials(client, rc, core, years)
        return filings

    async def _ngx_financials(
        self, client: httpx.AsyncClient, rc: str, core: str, years: int
    ) -> list[FinancialFiling]:
        term = core.replace("'", "''")
        params = {
            "$select": "URL,Created,Modified,CompanyName,CompanySymbol,Type_of_Submission",
            "$filter": (
                "Type_of_Submission eq 'Financial Statements' and "
                f"substringof('{term}',CompanyName)"
            ),
            "$orderby": "Created desc",
            "$top": "60",
        }
        resp = await client.get(
            self.NGX_LIST_API,
            params=params,
            headers={
                "Accept": "application/json;odata=verbose",
                "Referer": self.NGX_DISCLOSURES_URL,
            },
        )
        if resp.status_code >= 400:
            return []
        results = (resp.json().get("d") or {}).get("results") or []

        cutoff = datetime.utcnow().year - max(years, 1)
        filings: list[FinancialFiling] = []
        seen: set[str] = set()
        for item in results:
            ngx_name = str(item.get("CompanyName") or "")
            if core not in _core_name(ngx_name):
                continue
            url_field = item.get("URL") or {}
            doc_url = url_field.get("Url") if isinstance(url_field, dict) else None
            if not doc_url or not doc_url.lower().endswith(".pdf"):
                continue
            label = (
                (url_field.get("Description") if isinstance(url_field, dict) else "")
                or ""
            ) + " " + doc_url.rsplit("/", 1)[-1]
            year = _extract_year(label) or _year_of(item.get("Created"))
            if year is None or year <= cutoff:
                continue
            if doc_url in seen:
                continue
            seen.add(doc_url)
            filings.append(
                FinancialFiling(
                    company_id=rc,
                    year=year,
                    type=_classify_filing(label),
                    period_end=None,
                    currency="NGN",
                    document_url=doc_url,
                    document_format="pdf",
                    source_url=self.NGX_DISCLOSURES_URL,
                )
            )
        return filings


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _year_of(value: Any) -> int | None:
    d = _parse_date(value)
    return d.year if d else None


def _core_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
    words = [w for w in cleaned.split() if w]
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words).strip()


def _extract_year(text: str) -> int | None:
    for pattern in (
        r"FOR[_ ](20\d\d)",
        r"(20\d\d)[_ ]?(?:AUDITED|AFS)",
        r"(20\d\d)",
    ):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _classify_filing(text: str) -> FilingType:
    upper = text.upper()
    if any(k in upper for k in ("AUDITED", "AFS", "ANNUAL", "QUARTER 5", "QUARTER_5")):
        return FilingType.ANNUAL_REPORT
    return FilingType.BALANCE_SHEET
