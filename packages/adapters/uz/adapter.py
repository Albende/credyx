"""Uzbekistan adapter — UZSE liveness only.

Source landscape (all partial / non-API for the free MVP):

* **stat.uz** (State Statistics Committee) — publishes industry-level
  aggregates and a public legal-entity directory, but does not expose a
  documented JSON / REST endpoint and the web search is session-bound.
* **soliq.uz** (State Tax Committee) — provides a public INN ("STIR")
  lookup form, but the response is rendered by a logged-in portal flow
  and is not a stable scrape target. No public JSON contract.
* **UZSE** — https://uzse.uz/ — Republican Stock Exchange "Tashkent".
  Hosts disclosures for the ~120 listed issuers. The site is the only
  publicly browsable source of filed annual reports for Uzbek issuers,
  but the report URLs are session/page-numbered and not a clean JSON
  feed. We use UZSE for the health probe only.

What this adapter does today:

* `lookup_by_identifier` and `search_by_name` raise
  `AdapterNotImplementedError` — there is no free, documented endpoint
  that returns structured data for a given INN, and the spec forbids
  mock data.
* `fetch_financials` returns `[]` for every input — we never invent
  filings. A future Phase-2 UZSE scraper can populate listed-issuer
  reports here without changing the interface.
* `health_check` probes uzse.uz so operators can see when the upstream
  is reachable.

Identifier:
- VAT → INN ("STIR" in Uzbek; "ИНН" in Russian) — 9 digits assigned by
  the State Tax Committee. Same number serves as the VAT registration
  and the legal-entity tax ID.
"""
from __future__ import annotations

import logging
import re

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
    FinancialFiling,
    IdentifierType,
)

logger = logging.getLogger(__name__)

_INN_RE = re.compile(r"^\d{9}$")


def _normalize_inn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("UZ"):
        cleaned = cleaned[2:]
    if not _INN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Uzbekistan INN must be exactly 9 digits, got: {value}"
        )
    return cleaned


class UZAdapter(CountryAdapter):
    country_code = "UZ"
    country_name = "Uzbekistan"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    UZSE_BASE_URL = "https://uzse.uz"

    def _client(self):
        return build_http_client(
            base_url=self.UZSE_BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en,uz;q=0.7,ru;q=0.5",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"UZSE probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={
                "search": False,
                "lookup": False,
                "financials": False,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "UZSE reachable but no structured public endpoint is wired. "
                "stat.uz / soliq.uz do not expose documented JSON; "
                "registry lookup and name search are not implemented."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Uzbekistan name search is not available: stat.uz and soliq.uz "
            "do not expose a documented public search endpoint, and UZSE "
            "only covers ~120 listed issuers."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (
            IdentifierType.VAT,
            IdentifierType.COMPANY_NUMBER,
        ):
            raise InvalidIdentifierError(
                f"Uzbekistan adapter only supports VAT (INN) or "
                f"COMPANY_NUMBER, got {id_type}"
            )
        # Validate the INN shape even though we cannot resolve it — this gives
        # callers a fast 400-style error rather than a misleading 501.
        _normalize_inn(value)
        raise AdapterNotImplementedError(
            "Uzbekistan INN lookup is not available: soliq.uz STIR check "
            "requires a session-bound form flow and stat.uz has no public "
            "JSON contract."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Validate shape; if the caller passes garbage we surface that as a
        # 4xx-style InvalidIdentifierError instead of silently returning [].
        _normalize_inn(company_id)
        # UZSE is the only public source of filed annual reports for Uzbek
        # issuers, but its disclosure index is not a stable JSON feed yet.
        # Per spec we never invent filings, so listed-issuer support stays
        # behind a Phase-2 UZSE scraper. Empty list is the honest answer.
        return []
