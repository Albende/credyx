"""Oman adapter — MoCIIP registry + MSX (Muscat Stock Exchange).

The Ministry of Commerce, Industry and Investment Promotion (MoCIIP) exposes
a "Sijil" name search through https://www.moci.gov.om/ but no free public
JSON/REST API is published — partial data sits behind a session-bound search
form. We therefore do not pretend to support name search or CR-number lookup
yet, and raise `AdapterNotImplementedError` for both.

For listed issuers we fall back to MSX (https://www.msx.om/) where annual
reports are published for free. `fetch_financials` returns metadata pointing
to the MSX issuer profile; structured XBRL is not published, so
`structured_data` stays None and an LLM-readable PDF pipeline is needed
downstream.

Identifier candidates:
- CR Number (Commercial Registration), `COMPANY_NUMBER`
- TIN (Tax Identification Number), `VAT`
"""
from __future__ import annotations

import re

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterNotImplementedError
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

_MSX_TICKER_RE = re.compile(r"^[A-Z0-9]{2,8}$")

# MSX symbols for tickers we can route fetch_financials to. Anything outside
# this set falls back to an empty list — never invent filings.
_MSX_LISTED_TICKERS: frozenset[str] = frozenset(
    {
        "BKMB",  # Bank Muscat
        "OTEL",  # Omantel
        "OOMS",  # Oman Oil Marketing Company
        "NBOB",  # National Bank of Oman
    }
)


class OMAdapter(CountryAdapter):
    country_code = "OM"
    country_name = "Oman"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    MOCI_URL = "https://www.moci.gov.om/"
    MSX_URL = "https://www.msx.om/"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.MSX_URL, timeout=15.0) as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"MSX probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "MoCIIP Sijil search is session-bound and not exposed as JSON; "
                "name search and CR lookup not implemented. MSX annual reports "
                "available for listed issuers only."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Oman: MoCIIP Sijil search is session-bound (no public JSON API). "
            "Use MSX issuer profile URL for listed companies."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "Oman: no free public CR/TIN lookup. MoCIIP exposes only an "
            "interactive Sijil search; TIN validation needs the OTA portal."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = (company_id or "").strip().upper()
        if not _MSX_TICKER_RE.match(ticker) or ticker not in _MSX_LISTED_TICKERS:
            return []
        # MSX hosts annual reports as PDFs on per-issuer profile pages. We
        # return a single pointer filing — structured extraction is the
        # downstream PDF pipeline's job (pypdf + Celery, not in MVP).
        profile_url = f"{self.MSX_URL}en/Issuers/IssuerProfile/{ticker}"
        return [
            FinancialFiling(
                company_id=ticker,
                year=0,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="OMR",
                structured_data=None,
                document_url=None,
                document_format="pdf",
                source_url=profile_url,
            )
        ]
