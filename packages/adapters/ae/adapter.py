"""United Arab Emirates adapter.

The UAE has no single federal company registry. Records are split across
seven emirate-level Departments of Economic Development (Dubai DED, Abu
Dhabi DED, etc.) plus the two financial free zones (DIFC, ADGM). Each
maintains its own portal — most behind paid lookups, CAPTCHAs, or UAE
Pass authentication. The Federal Tax Authority publishes a TRN validator
but the endpoint requires a session cookie tied to an FTA account.

Free, machine-readable sources that exist today:

- Dubai Financial Market (DFM)              https://www.dfm.ae/
- Abu Dhabi Securities Exchange (ADX)       https://www.adx.ae/
- Federal Tax Authority TRN validator       https://eservices.tax.gov.ae/

DFM and ADX publish annual reports for listed issuers as free PDFs but
have no documented JSON API; scraping them requires a Playwright browser
pool (see `_base/browser.py` — not yet wired). Until that lands, the
adapter exposes:

- TRN normalization for callers that already hold a Tax Registration
  Number (15 digits, optionally prefixed "AE")
- A health probe against DFM's public homepage
- `fetch_financials` returns `[]` rather than fabricating PDFs
- `search_by_name` and `lookup_by_identifier` raise
  `AdapterNotImplementedError` so the API surface returns 501 — never a
  fake hit
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

_TRN_RE = re.compile(r"^\d{15}$")


def normalize_trn(value: str) -> str:
    """Normalize a UAE Tax Registration Number.

    Accepts forms like "100 1234 5678 9003", "AE100123456789003", etc.
    Returns 15 contiguous digits or raises `InvalidIdentifierError`.
    """
    cleaned = re.sub(r"\s+", "", value.strip().upper())
    if cleaned.startswith("AE"):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace("-", "")
    if not _TRN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"UAE TRN must be 15 digits (optionally AE-prefixed): {value}"
        )
    return cleaned


class AEAdapter(CountryAdapter):
    country_code = "AE"
    country_name = "United Arab Emirates"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    DFM_URL = "https://www.dfm.ae"
    ADX_URL = "https://www.adx.ae"

    _BLOCKED_NOTE = (
        "UAE company registries are fragmented across seven emirates (Dubai DED, "
        "Abu Dhabi DED, etc.) plus DIFC and ADGM. None expose a free public "
        "search/lookup API. Listed-issuer annual reports are available on DFM "
        "and ADX as free PDFs but require a browser-pool scraper (not yet "
        "wired)."
    )

    async def health_check(self) -> AdapterHealth:
        probe_error: str | None = None
        for url in (self.DFM_URL, self.ADX_URL):
            try:
                async with build_http_client(base_url=url) as client:
                    resp = await get_with_retry(client, "/")
                    if resp.status_code < 500:
                        probe_error = None
                        break
                    probe_error = f"{url} returned HTTP {resp.status_code}"
            except Exception as exc:
                probe_error = f"{url}: {str(exc)[:120]}"

        status = AdapterStatus.BLOCKED if probe_error is None else AdapterStatus.ERROR
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": False, "lookup": False, "financials": False},
            requires_api_key=self.requires_api_key,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=probe_error or self._BLOCKED_NOTE,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(self._BLOCKED_NOTE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            # Validate format so callers get a clear error early, but we still
            # cannot resolve the TRN to a company without an FTA session.
            normalize_trn(value)
        elif id_type == IdentifierType.COMPANY_NUMBER:
            if not value or not value.strip():
                raise InvalidIdentifierError("Trade licence number required")
        else:
            raise InvalidIdentifierError(
                f"UAE only supports VAT (TRN) or COMPANY_NUMBER, got {id_type}"
            )
        raise AdapterNotImplementedError(self._BLOCKED_NOTE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # DFM/ADX issuers publish annual report PDFs, but discovery requires a
        # JavaScript-rendered investor-relations page per issuer. Until the
        # browser pool lands we return [] rather than fabricate filings.
        return []
