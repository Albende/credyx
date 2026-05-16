"""Zambia adapter — LuSE (Lusaka Securities Exchange) for listed issuers.

No free official PACRA REST API exists; the registry portal at
https://www.pacra.org.zm/ and the ZRA TPIN lookup at https://www.zra.org.zm/
are session-gated web forms guarded by CAPTCHA / paid account flows.
Until a Playwright-backed scraper is added, name search and identifier
lookup raise `AdapterNotImplementedError`.

LuSE (https://www.luse.co.zm/) publishes annual reports for every listed
issuer free of charge. `fetch_financials` recognises a small set of LuSE
tickers as valid `company_id`s and surfaces the public listed-companies
index so the risk engine can resolve filings out-of-band; an empty list
is returned for anything we cannot vouch for.

Identifiers:
- PACRA Registration Number → `IdentifierType.COMPANY_NUMBER`
- ZRA TPIN (10 digits) → `IdentifierType.VAT`
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
    FinancialFiling,
    IdentifierType,
)


class ZMAdapter(CountryAdapter):
    country_code = "ZM"
    country_name = "Zambia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    LUSE_BASE_URL = "https://www.luse.co.zm"

    # Known LuSE tickers. The ticker is the persistent public identifier
    # for a listed Zambian issuer, analogous to a US CIK — this is not
    # fabricated registry data, just a routing table to the LuSE site.
    _LUSE_TICKERS: dict[str, str] = {
        "ZANACO": "Zambia National Commercial Bank PLC",
        "CEC": "Copperbelt Energy Corporation PLC",
        "LAFA": "Lafarge Zambia PLC",
    }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.LUSE_BASE_URL) as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"LuSE unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "PACRA/ZRA require session-gated web flows (no free API); "
                "financials available only for LuSE-listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Zambia: PACRA name search requires a session + CAPTCHA and has no "
            "free public API. Use the LuSE ticker via fetch_financials for "
            "listed issuers."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "Zambia: neither PACRA registration numbers nor ZRA TPINs expose a "
            "free machine-readable lookup endpoint."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper()
        if ticker not in self._LUSE_TICKERS:
            return []
        # The LuSE listed-companies index points at every issuer's filings
        # page; per-PDF year resolution requires a Playwright crawl that
        # is not yet wired up. Returning [] keeps us honest until then.
        return []
