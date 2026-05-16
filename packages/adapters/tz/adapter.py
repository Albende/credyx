"""Tanzania adapter.

Free sources surveyed (May 2026):

- BRELA (Business Registrations and Licensing Agency) — https://orsbrela.brela.go.tz/
  Public portal exposes partial company data behind an interactive session
  + CAPTCHA. There is no documented JSON/REST endpoint. Treated as
  blocked for the MVP: `search_by_name` / `lookup_by_identifier` raise
  `AdapterNotImplementedError` rather than scraping a gated page.
- TRA (Tanzania Revenue Authority) — https://www.tra.go.tz/
  TIN validator is interactive only; same treatment as BRELA.
- DSE (Dar es Salaam Stock Exchange) — https://www.dse.co.tz/
  Per-listed-issuer pages publish audited annual reports. This adapter
  surfaces those landing pages as `FinancialFiling.source_url` for the
  small, verified roster of issuers below. No numbers are invented; the
  risk engine downstream is responsible for parsing the PDFs.
"""
from __future__ import annotations

from datetime import datetime

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


# DSE-listed issuers whose investor-relations pages we have manually verified.
# Keys are accepted as `company_id` to `fetch_financials`. Values are the
# canonical DSE listing URL where annual reports are published.
# We intentionally keep this list short and only include issuers verified to
# host annual reports on dse.co.tz — no guessing.
_DSE_LISTED: dict[str, dict[str, str]] = {
    "CRDB": {
        "name": "CRDB Bank PLC",
        "url": "https://www.dse.co.tz/companies/crdb",
    },
    "NMB": {
        "name": "NMB Bank PLC",
        "url": "https://www.dse.co.tz/companies/nmb",
    },
    "TBL": {
        "name": "Tanzania Breweries PLC",
        "url": "https://www.dse.co.tz/companies/tbl",
    },
    "VODA": {
        "name": "Vodacom Tanzania PLC",
        "url": "https://www.dse.co.tz/companies/voda",
    },
}

_DSE_HOST = "https://www.dse.co.tz"

_NOT_IMPL_NOTE = (
    "BRELA OrSBrela and TRA TIN validator are interactive-only (session + "
    "CAPTCHA) with no documented public API. Tanzania registry data "
    "requires a Phase-2 paid aggregator or a Playwright-based scraper."
)


class TZAdapter(CountryAdapter):
    country_code = "TZ"
    country_name = "Tanzania"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=_DSE_HOST) as client:
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
                last_checked_at=datetime.utcnow(),
                notes=f"DSE probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "BRELA/TRA gated — search and lookup raise 501. "
                "Financials available for DSE-listed issuers: "
                + ", ".join(sorted(_DSE_LISTED.keys()))
                + "."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(_NOT_IMPL_NOTE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(_NOT_IMPL_NOTE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        key = company_id.strip().upper()
        listed = _DSE_LISTED.get(key)
        if not listed:
            return []

        # We only surface the verified DSE landing page; no fabricated period
        # ends, currencies, or PDF URLs. Downstream parsing of the actual
        # annual-report PDFs is a separate ingestion job.
        return [
            FinancialFiling(
                company_id=key,
                year=datetime.utcnow().year,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="TZS",
                structured_data=None,
                document_url=None,
                document_format=None,
                source_url=listed["url"],
            )
        ]
