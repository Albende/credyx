"""Kenya adapter — BRS / KRA / NSE.

Free official sources are heavily gated:

- **BRS (Business Registration Service)** via eCitizen (https://brs.go.ke/)
  requires a logged-in eCitizen account and charges per extract. The public
  name-search endpoint is JS-rendered and rate-limited behind a session
  cookie; no documented JSON API.
- **KRA iTax PIN checker** (https://itax.kra.go.ke/) is a server-side
  ASP.NET form protected by ViewState + CAPTCHA — not scrapable without
  a browser + OCR pipeline.
- **NSE (Nairobi Securities Exchange)** publishes free annual reports for
  the ~60 listed companies at https://www.nse.co.ke/. We surface a link
  to each listed issuer's investor-relations page as a best-effort
  filings source.

Identifiers:
- ``COMPANY_NUMBER``: BRS registration number, e.g. ``PVT-XXXXXXX``.
- ``VAT``: KRA PIN — starts with ``P``, then 9 digits, then a letter
  (e.g. ``P051092002G``). Used as the de-facto tax identifier.
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

_KRA_PIN_RE = re.compile(r"^[AP]\d{9}[A-Z]$")
_BRS_NUMBER_RE = re.compile(r"^[A-Z]{2,4}[-/]?[A-Z0-9]{5,12}$")

_NSE_BASE = "https://www.nse.co.ke"
_BRS_BASE = "https://brs.go.ke"


class KEAdapter(CountryAdapter):
    country_code = "KE"
    country_name = "Kenya"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        """Probe NSE then BRS; either reachable = OK (capabilities limited)."""
        notes_parts: list[str] = []
        nse_ok = await self._probe(_NSE_BASE)
        brs_ok = await self._probe(_BRS_BASE)
        if not nse_ok:
            notes_parts.append("NSE unreachable")
        if not brs_ok:
            notes_parts.append("BRS unreachable")

        if not nse_ok and not brs_ok:
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
                "financials": nse_ok,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "BRS/KRA gated (login + CAPTCHA + paid extracts). "
                "Financials limited to NSE-listed issuers."
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
            "Kenya name search requires a logged-in eCitizen session and is "
            "paid per extract. No free name-search API is available."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"Kenya supports COMPANY_NUMBER (BRS) or VAT (KRA PIN), got {id_type}"
            )
        cleaned = value.strip().upper().replace(" ", "")
        if id_type is IdentifierType.VAT and not _KRA_PIN_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"KRA PIN must match [A|P]NNNNNNNNNX, got: {value}"
            )
        if id_type is IdentifierType.COMPANY_NUMBER and not _BRS_NUMBER_RE.match(
            cleaned
        ):
            raise InvalidIdentifierError(
                f"BRS registration number format unrecognized: {value}"
            )
        raise AdapterNotImplementedError(
            "Kenya identifier lookup requires a logged-in BRS/eCitizen "
            "session (COMPANY_NUMBER) or an authenticated KRA iTax "
            "request behind CAPTCHA (VAT). Neither has a free API."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """Best-effort financials for NSE-listed issuers.

        Free filings on NSE are PDF annual reports posted on each issuer's
        company page. The page is JS-rendered (Vue.js shell) — without a
        Playwright browser pool we cannot deterministically extract real
        ``period_end`` / ``document_url`` per year. Per the no-mock-data
        rule we therefore return an empty list for now; once the PDF +
        browser pipeline lands, this is the natural integration point.
        Non-listed companies have no free filings source at all.
        """
        return []
