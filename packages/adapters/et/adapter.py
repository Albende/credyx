"""Ethiopia adapter — MoTI + ESX.

Free official sources are heavily limited:

- **MoTI (Ministry of Trade and Regional Integration)** at
  https://moti.gov.et/ exposes only partial public information about
  registered businesses. There is no documented JSON API for the
  commercial register; the e-services portal sits behind a session and
  Fayda national-ID authentication.
- **ESX (Ethiopian Securities Exchange)** at https://esxethiopia.com/
  launched in January 2024 as the country's first organised securities
  exchange. The number of listed issuers is currently very small
  (initial listings during 2024–2025), and issuer disclosure pages are
  JS-rendered. We surface ESX as the financials source for listed
  issuers; everything else returns ``[]``.

Identifiers:

- ``VAT`` / ``COMPANY_NUMBER`` are both modelled by the Ethiopian
  10-digit Taxpayer Identification Number (TIN) issued by the Ministry
  of Revenue. There is no separate company-register number with stable
  public lookup, so the TIN is the canonical identifier in scope.
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

_TIN_RE = re.compile(r"^\d{10}$")

_ESX_BASE = "https://esxethiopia.com"
_MOTI_BASE = "https://moti.gov.et"


class ETAdapter(CountryAdapter):
    country_code = "ET"
    country_name = "Ethiopia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        """Probe ESX then MoTI; either reachable = DEGRADED (limited capabilities)."""
        notes_parts: list[str] = []
        esx_ok = await self._probe(_ESX_BASE)
        moti_ok = await self._probe(_MOTI_BASE)
        if not esx_ok:
            notes_parts.append("ESX unreachable")
        if not moti_ok:
            notes_parts.append("MoTI unreachable")

        if not esx_ok and not moti_ok:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="; ".join(notes_parts),
            )

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={
                "search": False,
                "lookup": False,
                "financials": esx_ok,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "MoTI commercial register partial / session-gated; ESX "
                "launched 2024 with very few listed issuers. Financials "
                "limited to ESX-listed entities."
                + (f" [{'; '.join(notes_parts)}]" if notes_parts else "")
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
            "Ethiopia name search is not available: MoTI exposes only "
            "partial public information and has no documented free "
            "search API; ESX has too few listed issuers to back a "
            "general name-search endpoint."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Ethiopia supports VAT or COMPANY_NUMBER (TIN), got {id_type}"
            )
        cleaned = value.strip().replace(" ", "").replace("-", "")
        if not _TIN_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"Ethiopian TIN must be exactly 10 digits, got: {value}"
            )
        raise AdapterNotImplementedError(
            "Ethiopia TIN lookup requires the Ministry of Revenue e-tax "
            "portal which is session-gated behind Fayda national-ID "
            "authentication; no free JSON API is available."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """Best-effort financials.

        ESX launched in January 2024 and currently lists only a handful
        of issuers; disclosure pages are JS-rendered and would need the
        Playwright browser pool plus PDF extraction to surface real
        ``period_end`` / ``document_url`` per year. Per the no-mock-data
        rule we therefore return an empty list. Non-listed Ethiopian
        firms (state-owned giants like Ethiopian Airlines, Commercial
        Bank of Ethiopia, Ethio Telecom, Awash Bank) have no free
        machine-readable filings source at all today.
        """
        return []
