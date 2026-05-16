"""Egypt adapter — GAFI / ETA / EGX.

There is no free official JSON API for the Egyptian commercial register or
the Egyptian Tax Authority. GAFI's investor portal (gafi.gov.eg) and the
ETA tax-verifier expose limited data behind interactive web forms; both
require sessioned access we cannot replicate without paid scraping infra.

For listed companies, the Egyptian Stock Exchange (egx.com.eg) publishes
annual reports and disclosures for free. This adapter therefore:

- raises ``AdapterNotImplementedError`` for ``search_by_name`` and
  ``lookup_by_identifier`` (no clean free national source);
- returns the EGX disclosure page URL as a single best-effort filing
  pointer when a ticker is supplied to ``fetch_financials`` — actual PDF
  scraping/parsing is left to the PDF pipeline.

Identifiers:
- ``COMPANY_NUMBER`` — Commercial Registration Number (variable digits)
- ``VAT``           — ETA Tax ID (9 digits, often shown ``NNN-NNN-NNN``)
"""
from __future__ import annotations

import re
from datetime import datetime

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
)

_TAX_ID_RE = re.compile(r"^\d{9}$")
# EGX tickers are 3–6 uppercase Latin letters (e.g. COMI, ETEL, EAST, TMGH).
_EGX_TICKER_RE = re.compile(r"^[A-Z]{2,6}$")

_NAME_UNAVAILABLE = (
    "Egypt: no free public name-search API. GAFI investor portal and ETA "
    "tax verifier are interactive web forms behind session/captcha gates."
)
_LOOKUP_UNAVAILABLE = (
    "Egypt: identifier lookup not available via free APIs. CR records are "
    "served only through GAFI's gated portal; ETA tax verifier returns "
    "data only after captcha-protected form submission."
)


def _normalize_tax_id(value: str) -> str:
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if not _TAX_ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Egyptian Tax ID must be 9 digits (e.g. 200-118-815): {value}"
        )
    return cleaned


def _normalize_ticker(value: str) -> str | None:
    cleaned = value.strip().upper()
    if _EGX_TICKER_RE.match(cleaned):
        return cleaned
    return None


class EGAdapter(CountryAdapter):
    country_code = "EG"
    country_name = "Egypt"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    EGX_BASE_URL = "https://www.egx.com.eg"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "GAFI/ETA gated — search and lookup not available. "
            "EGX disclosure links surfaced for listed tickers only."
        )
        try:
            async with build_http_client(base_url=self.EGX_BASE_URL) as client:
                resp = await get_with_retry(client, "/en/")
                reachable = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes=f"EGX unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED if reachable else AdapterStatus.ERROR,
            capabilities={
                "search": False,
                "lookup": False,
                "financials": reachable,
            },
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(_NAME_UNAVAILABLE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            _normalize_tax_id(value)
        elif id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"EG supports COMPANY_NUMBER and VAT, got {id_type}"
            )
        raise AdapterNotImplementedError(_LOOKUP_UNAVAILABLE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = _normalize_ticker(company_id)
        if not ticker:
            # Non-listed companies have no free filings source in Egypt.
            return []

        # EGX exposes per-issuer disclosure pages; we return a single
        # pointer rather than fabricating year-by-year structured data.
        source_url = (
            f"{self.EGX_BASE_URL}/en/ListedStocksOverview.aspx?Isin={ticker}"
        )
        document_url = (
            f"{self.EGX_BASE_URL}/en/CompanyProfile.aspx?Symbol={ticker}"
        )
        current_year = datetime.utcnow().year
        return [
            FinancialFiling(
                company_id=ticker,
                year=current_year,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="EGP",
                structured_data=None,
                document_url=document_url,
                document_format="html",
                source_url=source_url,
            )
        ]
