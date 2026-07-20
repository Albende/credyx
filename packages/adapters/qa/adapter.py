"""Qatar adapter — GLEIF registry search/lookup + QSE financial statements.

Qatar has no free public JSON API for the Ministry of Commerce and Industry
(MoCI) Commercial Registration database: the eServices lookups are bound to a
Tawtheeq (national e-ID) session and the General Tax Authority TIN validator is
reCAPTCHA-gated. Two free, key-free sources cover the gap:

* GLEIF (Global LEI Foundation, JSON:API) indexes every LEI-holding Qatari
  entity — listed issuers, banks, funds, regulated and W.L.L. firms — with the
  registered legal name, address, legal form and, crucially, the MoCI
  Commercial Registration number in the ``entity.registeredAs`` field. This
  drives QA-scoped name search and CR lookup.
* Qatar Stock Exchange (QSE, https://www.qe.com.qa/) publishes two things
  without auth: ``/wp/mw/data/MarketWatch.txt`` — a JSON snapshot of every
  listed security (symbol, English/Arabic name, sector) — and the
  ``/qdisclosure/api/XBRL/GetFSAttachmentAPI`` endpoint, which returns the
  actual filed financial-statement PDF for a given ``symCode`` + quarter-end
  ``reportEndDate``. Those are the real audited accounts, not a landing page.

So ``search_by_name`` merges QSE listed-company matches (which carry the ticker
needed for financials) with GLEIF full-text results; ``lookup_by_identifier``
resolves a CR number to its GLEIF record; ``fetch_financials`` takes a QSE
ticker and returns the annual financial-statement documents that actually
download for that specific issuer. Per the project rules, gated capabilities
(TIN lookup) raise ``AdapterNotImplementedError`` rather than fabricate data.

Identifiers:

* CR Number — 4-8 digit Commercial Registration, ``IdentifierType.COMPANY_NUMBER``.
* TIN — General Tax Authority Tax Identification Number, mapped to
  ``IdentifierType.VAT`` (Qatar runs no VAT regime; the TIN slot is the closest
  contract match). The adapter strips an optional ``QA`` prefix.
* QSE Ticker — 2-8 uppercase letters (e.g. ``QNBK``, ``IQCD``), optionally
  prefixed ``QSE:``, accepted by ``fetch_financials``.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
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

_CR_RE = re.compile(r"^\d{4,10}$")
_TIN_RE = re.compile(r"^\d{8,13}$")
_TICKER_RE = re.compile(r"^[A-Z]{2,8}$")

_QSE_LISTED_COMPTYPES = {"COMP", "QFC", "ETF", "V"}


def _normalize_cr(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _CR_RE.match(cleaned):
        raise InvalidIdentifierError(f"Qatar CR must be 4-10 digits, got: {value}")
    return cleaned


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("QA"):
        cleaned = cleaned[2:]
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(f"Qatar TIN must be 8-13 digits, got: {value}")
    return cleaned


def _normalize_ticker(value: str) -> str | None:
    cleaned = value.strip().upper()
    if cleaned.startswith("QSE:"):
        cleaned = cleaned[4:]
    if not _TICKER_RE.match(cleaned):
        return None
    return cleaned


class QAAdapter(CountryAdapter):
    country_code = "QA"
    country_name = "Qatar"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
    QSE_BASE = "https://www.qe.com.qa"
    QSE_MARKETWATCH_URL = "https://www.qe.com.qa/wp/mw/data/MarketWatch.txt"
    QSE_FS_API = "https://www.qe.com.qa/qdisclosure/api/XBRL/GetFSAttachmentAPI"
    QSE_FS_PAGE = "https://www.qe.com.qa/financial-statements"
    QSE_LISTED_PAGE = "https://www.qe.com.qa/listed-companies"

    async def health_check(self) -> AdapterHealth:
        try:
            records = await self._gleif_query(
                {"filter[entity.legalAddress.country]": "QA", "page[size]": 1}
            )
            gleif_ok = bool(records)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"GLEIF probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if gleif_ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + CR lookup via GLEIF (LEI-holding QA entities); "
                "financials are real filed FS PDFs from the QSE q-disclosure "
                "API for listed tickers. MoCI CR detail + GTA TIN are gated "
                "(Tawtheeq / reCAPTCHA) so TIN lookup raises 501."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = name.strip()
        if not term:
            raise InvalidIdentifierError("Empty search term")

        matches: list[CompanyMatch] = []
        seen: set[str] = set()

        for row in await self._qse_listed_rows():
            company = str(row.get("CompanyEN") or "").strip()
            symbol = str(row.get("Symbol") or "").strip().upper()
            if not symbol or not company:
                continue
            if term.lower() not in company.lower() and term.lower() not in symbol.lower():
                continue
            key = symbol
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                CompanyMatch(
                    id=symbol,
                    name=company,
                    country="QA",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.OTHER, value=symbol, label="QSE Ticker"
                        )
                    ],
                    address=str(row.get("SectorEN") or "").strip() or None,
                    status="active",
                    source_url=self.QSE_LISTED_PAGE,
                )
            )
            if len(matches) >= limit:
                return matches

        records = await self._gleif_query(
            {
                "filter[fulltext]": term,
                "filter[entity.legalAddress.country]": "QA",
                "page[size]": max(1, min(int(limit), 50)),
                "page[number]": 1,
            }
        )
        for record in records:
            match = self._gleif_record_to_match(record)
            if match is None or match.id in seen:
                continue
            seen.add(match.id)
            matches.append(match)
            if len(matches) >= limit:
                break

        if not matches:
            raise AdapterNotImplementedError(
                f"No QSE-listed or LEI-holding Qatari entity matched '{name}'. "
                "Qatar has no free authoritative full-registry name search — the "
                "MoCI Commercial Registration lookup is Tawtheeq-gated. Coverage "
                "is limited to listed issuers (QSE) and LEI holders (GLEIF)."
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            cr = _normalize_cr(value)
            record = await self._gleif_by_registered_as(cr)
            if not record:
                return None
            return self._gleif_record_to_details(record, cr)
        if id_type == IdentifierType.VAT:
            _normalize_tin(value)
            raise AdapterNotImplementedError(
                "Qatar GTA TIN validator is reCAPTCHA-protected and no free "
                "public source indexes TINs; look up by CR (COMPANY_NUMBER)."
            )
        raise InvalidIdentifierError(
            f"Qatar supports COMPANY_NUMBER (CR) and VAT (TIN), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = _normalize_ticker(company_id)
        if ticker is None:
            _normalize_cr(company_id)
            return []

        wanted = max(1, years)
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []

        async with build_http_client(timeout=45.0) as client:
            for year in range(current_year, current_year - wanted - 2, -1):
                period_end = date(year, 12, 31)
                document_url = self._fs_url(ticker, period_end, attachment_type=1)
                if not await self._fs_pdf_exists(client, document_url):
                    document_url = self._fs_url(ticker, period_end, attachment_type=3)
                    if not await self._fs_pdf_exists(client, document_url):
                        continue
                filings.append(
                    FinancialFiling(
                        company_id=ticker,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=period_end,
                        currency="QAR",
                        document_url=document_url,
                        document_format="pdf",
                        source_url=self.QSE_FS_PAGE,
                    )
                )
                if len(filings) >= wanted:
                    break

        return filings

    def _fs_url(self, ticker: str, period_end: date, *, attachment_type: int) -> str:
        return (
            f"{self.QSE_FS_API}?attachmentType={attachment_type}"
            f"&symCode={ticker}&reportEndDate={period_end.isoformat()}&lang=1"
        )

    @staticmethod
    async def _fs_pdf_exists(client: httpx.AsyncClient, url: str) -> bool:
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return False
                return resp.headers.get("content-type", "").lower().startswith(
                    "application/pdf"
                )
        except (httpx.TransportError, httpx.TimeoutException):
            return False

    async def _qse_listed_rows(self) -> list[dict[str, Any]]:
        try:
            async with build_http_client(timeout=30.0) as client:
                resp = await get_with_retry(client, self.QSE_MARKETWATCH_URL)
                if resp.status_code != 200:
                    return []
                payload = resp.json()
        except (httpx.HTTPError, ValueError):
            return []
        rows = payload.get("rows") or []
        return [r for r in rows if r.get("CompType") in _QSE_LISTED_COMPTYPES]

    async def _gleif_query(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/vnd.api+json"}
        ) as client:
            resp = await get_with_retry(client, self.GLEIF_URL, params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("data") or []

    async def _gleif_by_registered_as(self, cr: str) -> dict[str, Any] | None:
        records = await self._gleif_query(
            {
                "filter[entity.registeredAs]": cr,
                "filter[entity.legalAddress.country]": "QA",
                "page[size]": 1,
            }
        )
        return records[0] if records else None

    def _gleif_record_to_match(self, record: dict[str, Any]) -> CompanyMatch | None:
        lei = record.get("id") or _safe_get(record, "attributes", "lei")
        if not lei:
            return None
        entity = _safe_get(record, "attributes", "entity") or {}
        name = _safe_get(entity, "legalName", "name")
        if not name:
            return None
        cr = entity.get("registeredAs")
        identifiers = [
            RegistryIdentifier(type=IdentifierType.LEI, value=str(lei), label="LEI")
        ]
        if cr:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=str(cr), label="CR"
                )
            )
        status_raw = (entity.get("status") or "").upper()
        return CompanyMatch(
            id=str(cr) if cr else str(lei),
            name=str(name),
            country="QA",
            identifiers=identifiers,
            address=_format_gleif_address(entity.get("legalAddress")),
            status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
            source_url=f"https://search.gleif.org/#/record/{lei}",
        )

    def _gleif_record_to_details(
        self, record: dict[str, Any], cr: str
    ) -> CompanyDetails:
        lei = record.get("id") or _safe_get(record, "attributes", "lei")
        entity = _safe_get(record, "attributes", "entity") or {}
        name = _safe_get(entity, "legalName", "name") or cr
        legal_form = _safe_get(entity, "legalForm", "id")
        status_raw = (entity.get("status") or "").upper()
        identifiers = [
            RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=cr, label="CR")
        ]
        if lei:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.LEI, value=str(lei), label="LEI")
            )
        return CompanyDetails(
            id=cr,
            name=str(name),
            country="QA",
            legal_form=str(legal_form) if legal_form else None,
            status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
            registered_address=_format_gleif_address(entity.get("legalAddress")),
            identifiers=identifiers,
            raw=record,
            source_url=(
                f"https://search.gleif.org/#/record/{lei}" if lei else None
            ),
        )


def _safe_get(obj: Any, *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _format_gleif_address(address: Any) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    for key in ("city", "region", "postalCode", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None
