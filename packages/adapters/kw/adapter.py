"""Kuwait adapter — Boursa Kuwait listed-company filings.

MoCI (Ministry of Commerce & Industry, https://www.moci.gov.kw/) exposes a
partial public CR lookup that requires interactive web flows and is not
suitable for a free, deterministic adapter in the MVP. Search/lookup are
therefore not implemented; financials are surfaced for listed companies
through Boursa Kuwait (https://www.boursakuwait.com.kw/), which publishes
annual reports for free.

Identifier:
- CR Number (Commercial Registration) for entities — `COMPANY_NUMBER`.
- For Boursa-listed firms we accept the ticker symbol (NBK, ZAIN, AGLT,
  KFH, …) as `company_id` to `fetch_financials`.
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


class KWAdapter(CountryAdapter):
    country_code = "KW"
    country_name = "Kuwait"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    BOURSA_BASE_URL = "https://www.boursakuwait.com.kw"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BOURSA_BASE_URL) as client:
                resp = await get_with_retry(client, "/")
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED if ok else AdapterStatus.ERROR,
            capabilities={"search": False, "lookup": False, "financials": ok},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "MoCI lacks a public structured API; search/lookup not "
                "implemented. Financials available only for Boursa-listed "
                "companies via ticker."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "MoCI Kuwait does not expose a free structured search API; "
            "name search unavailable in MVP."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "MoCI Kuwait does not expose a free structured CR lookup API; "
            "identifier lookup unavailable in MVP."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper()
        if not ticker:
            return []

        # Boursa Kuwait publishes per-issuer disclosure pages under
        # /en/issuer/{TICKER}; we surface the canonical landing URL so the
        # caller can fetch the PDF annual report manually. We do NOT
        # fabricate per-year filings — only a single pointer is returned
        # when the issuer page is reachable.
        url = f"{self.BOURSA_BASE_URL}/en/issuer/{ticker}"
        try:
            async with build_http_client(base_url=self.BOURSA_BASE_URL) as client:
                resp = await get_with_retry(client, f"/en/issuer/{ticker}")
        except Exception:
            return []
        if resp.status_code >= 400:
            return []

        return [
            FinancialFiling(
                company_id=ticker,
                year=0,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="KWD",
                structured_data=None,
                document_url=None,
                document_format="html",
                source_url=url,
            )
        ]
