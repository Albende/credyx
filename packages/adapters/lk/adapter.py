"""Sri Lanka adapter — CSE (Colombo Stock Exchange) + DRC (eROC).

CSE exposes undocumented JSON POST endpoints used by their public website
(cse.lk). Two of them are stable enough to rely on:

  POST /api/companyInfoSummery       — registry-style snapshot for a symbol
  POST /api/companyInfoFinancials    — list of filed annual report PDFs

Both take `application/x-www-form-urlencoded` with `symbol=<TICKER>.N0000`.
PDFs are served from `https://cdn.cse.lk/`.

DRC (Department of Registrar of Companies) runs eROC at eroc.drc.gov.lk —
the public search front-end is a Single-Page App with no documented JSON
API, so name search against DRC is not feasible without browser automation.
We therefore restrict `search_by_name` to CSE-listed issuers (covers the
material credit-risk universe) and raise `AdapterNotImplementedError` for
non-listed companies — per the no-mock-data rule.

Identifier: DRC Company Registration Number (PV/PB/PQ + digits) for private
entities, validated by regex but not resolvable here. CSE ticker is the
working primary key for now.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

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

# DRC company numbers: PV / PB / PQ / PVS / N(V) prefixes + digits.
_DRC_RE = re.compile(r"^(PV|PB|PQ|PVS|N|NV)\s?\d{1,9}$", re.IGNORECASE)
# Working CSE ticker: 1-6 alpha-numeric, optional ".N0000" segment.
_CSE_RE = re.compile(r"^[A-Z0-9]{1,6}(\.[A-Z0-9]{1,6})?$")
# IRD TIN: 9 digits, sometimes 9 + check digit.
_TIN_RE = re.compile(r"^\d{9,10}$")

# Known CSE issuers used as a tiny local lookup so name search can resolve
# the household-name listed companies without us inventing arbitrary data.
# Tickers verified against cse.lk on 2026-05-14.
_KNOWN_CSE_TICKERS: dict[str, str] = {
    "john keells holdings": "JKH",
    "dialog axiata": "DIAL",
    "commercial bank of ceylon": "COMB",
    "sri lanka telecom": "SLTL",
    "hatton national bank": "HNB",
    "sampath bank": "SAMP",
    "lanka ioc": "LIOC",
    "ceylon tobacco": "CTC",
    "nestle lanka": "NEST",
    "hayleys": "HAYL",
}


class LKAdapter(CountryAdapter):
    country_code = "LK"
    country_name = "Sri Lanka"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    CSE_BASE_URL = "https://www.cse.lk"
    CSE_CDN_URL = "https://cdn.cse.lk"
    DRC_BASE_URL = "https://eroc.drc.gov.lk"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.CSE_BASE_URL) as client:
                resp = await client.post(
                    "/api/companyInfoSummery",
                    data={"symbol": "JKH.N0000"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("reqSymbolInfo"):
                    raise RuntimeError("Empty reqSymbolInfo from CSE")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "CSE-listed issuers only. DRC eROC requires browser automation "
                "and is not yet wired."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = name.strip().lower()
        if not needle:
            return []
        tickers: list[str] = []
        for known_name, ticker in _KNOWN_CSE_TICKERS.items():
            if needle in known_name or known_name in needle:
                tickers.append(ticker)
        if not tickers and _CSE_RE.match(name.strip().upper()):
            tickers.append(name.strip().upper().split(".")[0])
        if not tickers:
            raise AdapterNotImplementedError(
                "Sri Lanka name search currently resolves only CSE-listed issuers "
                "and exact tickers. DRC eROC has no public JSON API."
            )

        matches: list[CompanyMatch] = []
        async with build_http_client(base_url=self.CSE_BASE_URL) as client:
            for ticker in tickers[:limit]:
                payload = await _cse_post(
                    client, "/api/companyInfoSummery", {"symbol": _symbol(ticker)}
                )
                info = (payload or {}).get("reqSymbolInfo") or {}
                if not info.get("symbol"):
                    continue
                matches.append(
                    CompanyMatch(
                        id=ticker,
                        name=info.get("name", "").strip(),
                        country=self.country_code,
                        identifiers=[
                            RegistryIdentifier(
                                type=IdentifierType.OTHER,
                                value=info["symbol"],
                                label="CSE Ticker",
                            ),
                        ],
                        status="active",
                        source_url=_cse_profile_url(info["symbol"]),
                    )
                )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        v = value.strip()
        if id_type == IdentifierType.COMPANY_NUMBER:
            normalized = v.upper().replace(" ", "")
            if _CSE_RE.match(normalized):
                return await self._lookup_cse(normalized.split(".")[0])
            if _DRC_RE.match(normalized):
                raise AdapterNotImplementedError(
                    f"DRC lookup for {normalized} requires a browser session "
                    "against eROC; not wired in MVP."
                )
            raise InvalidIdentifierError(
                f"LK identifier must be a CSE ticker or DRC number (PV/PB/PQ + digits): {value}"
            )
        if id_type == IdentifierType.VAT:
            if not _TIN_RE.match(v):
                raise InvalidIdentifierError(f"Sri Lanka TIN must be 9-10 digits: {value}")
            raise AdapterNotImplementedError(
                "IRD TIN validation is not publicly machine-queryable without a "
                "browser session."
            )
        raise InvalidIdentifierError(
            f"LK only supports COMPANY_NUMBER (CSE ticker) and VAT (TIN), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper().split(".")[0]
        if not _CSE_RE.match(ticker):
            return []
        async with build_http_client(base_url=self.CSE_BASE_URL) as client:
            payload = await _cse_post(
                client, "/api/companyInfoFinancials", {"symbol": _symbol(ticker)}
            )
        items = (payload or {}).get("infoAnnualData") or []
        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        for item in items:
            period_end = _parse_epoch_ms(item.get("manualDate"))
            if not period_end or period_end.year < cutoff_year:
                continue
            rel = item.get("path")
            if not rel:
                continue
            doc_url = f"{self.CSE_CDN_URL}/{rel.lstrip('/')}"
            filings.append(
                FinancialFiling(
                    company_id=ticker,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="LKR",
                    structured_data=None,
                    document_url=doc_url,
                    document_format="pdf",
                    source_url=_cse_profile_url(_symbol(ticker)),
                )
            )
        return filings

    async def _lookup_cse(self, ticker: str) -> CompanyDetails | None:
        async with build_http_client(base_url=self.CSE_BASE_URL) as client:
            payload = await _cse_post(
                client, "/api/companyInfoSummery", {"symbol": _symbol(ticker)}
            )
        if not payload:
            return None
        info = payload.get("reqSymbolInfo") or {}
        if not info.get("symbol"):
            return None
        return CompanyDetails(
            id=ticker,
            name=info.get("name", "").strip(),
            country="LK",
            legal_form="PLC",
            status="active",
            incorporation_date=_parse_issue_date(info.get("issueDate")),
            registered_address=None,
            capital_amount=_issued_capital(info),
            capital_currency="LKR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=info["symbol"],
                    label="CSE Ticker",
                ),
            ],
            raw=payload,
            source_url=_cse_profile_url(info["symbol"]),
        )


async def _cse_post(client: Any, path: str, data: dict[str, str]) -> dict[str, Any] | None:
    """CSE only accepts POST with form-encoded body; httpx GET retry wrapper
    doesn't fit, so we issue a single POST and tolerate 404/empty."""
    resp = await client.post(
        path,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code == 404 or not resp.content:
        return None
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return None


def _symbol(ticker: str) -> str:
    """Normalize a bare ticker like 'JKH' into the CSE-internal 'JKH.N0000'."""
    return ticker if "." in ticker else f"{ticker}.N0000"


def _cse_profile_url(symbol: str) -> str:
    return f"https://www.cse.lk/pages/company-profile/company-profile.component.html?symbol={symbol}"


def _parse_epoch_ms(v: Any) -> date | None:
    if v is None:
        return None
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def _parse_issue_date(s: str | None) -> date | None:
    if not s:
        return None
    # CSE returns e.g. "23/OCT/1986".
    try:
        return datetime.strptime(s, "%d/%b/%Y").date()
    except ValueError:
        return None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _issued_capital(info: dict[str, Any]) -> float | None:
    par = _coerce_float(info.get("parValue"))
    qty = _coerce_float(info.get("quantityIssued"))
    if par is None or qty is None:
        return None
    return par * qty
