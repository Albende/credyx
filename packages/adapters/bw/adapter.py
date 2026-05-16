"""Botswana adapter — CIPA registry + BSE listed-company filings.

Free public sources only:
- CIPA (Companies and Intellectual Property Authority) at cipa.co.bw and
  the e-services portal eservices.cipa.co.bw expose only partial data
  through interactive web forms gated by reCAPTCHA — search and lookup
  cannot be done robustly without paying or breaking ToS.
- BURS (tax authority) does not expose a public VAT/TIN lookup.
- BSE (Botswana Stock Exchange) at bse.co.bw publishes annual reports for
  listed issuers as free PDFs. For listed tickers we surface the issuer
  page as a `FinancialFiling` pointer; deeper PDF parsing is left to the
  cross-cutting PDF pipeline.

Identifier: CIPA company registration number. The BSE ticker is also
accepted (treated as COMPANY_NUMBER) for the listed-company path.
"""
from __future__ import annotations

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

# Known BSE-listed issuer tickers we can build a deep-link for. Mapping is the
# minimal handful from the country doc — extend as new tickers are confirmed.
_BSE_LISTED: dict[str, str] = {
    "FNBB": "First National Bank Botswana",
    "SEFA": "Sefalana Holding Company",
    "CHOP": "Choppies Enterprises",
    "LHL": "Letshego Holdings",
}


class BWAdapter(CountryAdapter):
    country_code = "BW"
    country_name = "Botswana"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    CIPA_URL = "https://www.cipa.co.bw"
    BSE_URL = "https://www.bse.co.bw"

    async def health_check(self) -> AdapterHealth:
        # BSE is the only source we can actually exercise; CIPA is reCAPTCHA-gated.
        try:
            async with build_http_client(base_url=self.BSE_URL) as client:
                resp = await get_with_retry(client, "/")
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=f"BSE probe failed: {str(exc)[:160]}",
            )
        status = AdapterStatus.DEGRADED if ok else AdapterStatus.ERROR
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "CIPA registry is reCAPTCHA-gated; BURS has no public lookup. "
                "Only BSE-listed issuers expose free annual reports."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Botswana CIPA name search is reCAPTCHA-gated; no free programmatic source."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "Botswana CIPA registry lookup is reCAPTCHA-gated; "
            "BURS VAT validation has no public endpoint."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper()
        if ticker not in _BSE_LISTED:
            return []
        # We surface a single pointer to the BSE issuer page rather than guessing
        # PDF URLs; the cross-cutting PDF pipeline is responsible for scraping
        # the year-by-year annual reports off this page.
        source_url = f"{self.BSE_URL}/issuers/{ticker.lower()}"
        return [
            FinancialFiling(
                company_id=ticker,
                year=0,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="BWP",
                structured_data=None,
                document_url=None,
                document_format="html",
                source_url=source_url,
            )
        ]
