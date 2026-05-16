"""Bahrain adapter — MoIC + Bahrain Bourse listed-company filings.

The Ministry of Industry and Commerce (https://www.moic.gov.bh/) exposes
only a partial public CR (Commercial Registration) lookup driven by
interactive web forms; there is no documented free structured API, so
deterministic search / identifier lookup is not implementable in the MVP.

Bahrain Bourse (https://www.bahrainbourse.com/) publishes free annual
reports for listed issuers on per-issuer disclosure pages, so
`fetch_financials` surfaces a canonical pointer for listed firms keyed by
the bourse ticker (e.g. ``BATELCO``, ``AUB``, ``ALBH``, ``GFH``). Per the
project rules we never fabricate filings — unlisted or unreachable
issuers return an empty list.

Identifiers:

* CR Number — Commercial Registration, encoded as ``COMPANY_NUMBER``.
* VAT — NBR-issued Bahrain VAT account number (15 digits beginning with
  ``2``). Stored under ``IdentifierType.VAT``.
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


class BHAdapter(CountryAdapter):
    country_code = "BH"
    country_name = "Bahrain"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    MOIC_BASE_URL = "https://www.moic.gov.bh"
    BOURSE_BASE_URL = "https://www.bahrainbourse.com"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BOURSE_BASE_URL, timeout=10.0) as client:
                resp = await get_with_retry(client, "/", max_attempts=1)
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED if ok else AdapterStatus.ERROR,
            capabilities={"search": False, "lookup": False, "financials": ok},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "MoIC Bahrain lacks a public structured API; search/lookup "
                "not implemented. Financials available only for Bahrain "
                "Bourse-listed issuers via ticker."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "MoIC Bahrain does not expose a free structured search API; "
            "name search unavailable in MVP."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "MoIC Bahrain does not expose a free structured CR/VAT lookup "
            "API; identifier lookup unavailable in MVP."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper()
        if not ticker:
            return []

        # Bahrain Bourse serves per-issuer disclosure landing pages; we
        # surface only the canonical URL so the caller can retrieve the
        # PDF annual report. Per-year structured filings require deeper
        # page parsing which is out of scope for the MVP — never fabricate
        # additional rows.
        path = f"/issuer-profile/{ticker}"
        try:
            async with build_http_client(base_url=self.BOURSE_BASE_URL) as client:
                resp = await get_with_retry(client, path)
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
                currency="BHD",
                structured_data=None,
                document_url=None,
                document_format="html",
                source_url=f"{self.BOURSE_BASE_URL}{path}",
            )
        ]
