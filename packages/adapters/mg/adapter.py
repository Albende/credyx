"""Madagascar adapter — EDBM.

Madagascar's company data is fragmented and only partially public:

- **EDBM (Economic Development Board of Madagascar)** at https://edbm.mg/
  is the official one-stop-shop for company incorporation and offers a
  partial public-search interface. The portal is JS-rendered and there
  is no documented free JSON API; structured extracts and certified
  documents are issued in-person or for a fee.
- There is **no stock exchange** in Madagascar, so unlike most countries
  there is no listed-issuer free-filings fallback.

Identifiers:
- ``VAT``: NIF (Numéro d'Identification Fiscale) — taxpayer ID issued
  by the DGI (Direction Générale des Impôts). Typically a numeric string.
- ``COMPANY_NUMBER``: STAT (Numéro Statistique) — statistical ID issued
  by INSTAT. A 17-character code combining sector, region and a sequence.
"""
from __future__ import annotations

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

_NIF_RE = re.compile(r"^\d{7,12}$")
_STAT_RE = re.compile(r"^[0-9A-Z]{10,20}$")

_EDBM_BASE = "https://edbm.mg"


class MGAdapter(CountryAdapter):
    country_code = "MG"
    country_name = "Madagascar"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 20

    async def health_check(self) -> AdapterHealth:
        """Probe edbm.mg; reachable = DEGRADED (capabilities limited)."""
        edbm_ok = await self._probe(_EDBM_BASE)

        if not edbm_ok:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="EDBM unreachable",
            )

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": False},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "EDBM portal is JS-rendered with no free JSON API; structured "
                "extracts are paid/in-person. No stock exchange — no listed "
                "filings fallback."
            ),
        )

    async def _probe(self, base_url: str) -> bool:
        try:
            async with build_http_client(base_url=base_url, timeout=10.0) as client:
                resp = await get_with_retry(client, "/", max_attempts=1)
                return resp.status_code < 500
        except Exception:
            return False

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Madagascar name search requires interactive use of the EDBM "
            "portal (JS-rendered, no free JSON API). A Playwright-backed "
            "scraper is needed before this can be implemented."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Madagascar supports VAT (NIF) or COMPANY_NUMBER (STAT), got {id_type}"
            )
        cleaned = value.strip().upper().replace(" ", "")
        if id_type is IdentifierType.VAT and not _NIF_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"Madagascar NIF must be 7–12 digits, got: {value}"
            )
        if id_type is IdentifierType.COMPANY_NUMBER and not _STAT_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"Madagascar STAT number format unrecognized: {value}"
            )
        raise AdapterNotImplementedError(
            "Madagascar identifier lookup requires the EDBM portal or DGI "
            "in-person request. No free structured API is available."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """No free filings source exists for Madagascar.

        There is no stock exchange, EDBM does not publish balance sheets,
        and the commercial-court filings are only available on-site for a
        fee. Per the no-mock-data rule we return an empty list rather
        than fabricate filings.
        """
        return []
