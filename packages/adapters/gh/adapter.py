"""Ghana adapter — RGD + GRA + GSE.

Free official sources are heavily gated:

- **RGD (Registrar General's Department)** at https://rgd.gov.gh/ and the
  eRegistrar portal https://eregistrar.rgd.gov.gh/ expose a public name
  search shell, but the underlying result feed is session-bound XHR and
  full extracts are paid per document. There is no documented free JSON
  API.
- **GRA (Ghana Revenue Authority) TIN** validator at https://gra.gov.gh/
  is a server-side form behind a CAPTCHA / session token; no free
  TIN→company resolution.
- **GSE (Ghana Stock Exchange)** at https://gse.com.gh/ freely publishes
  annual reports for the ~40 listed issuers, but per-issuer pages are
  JS-rendered and per-year PDF links are not stably addressable without
  a browser pool.

Identifiers:
- ``COMPANY_NUMBER``: RGD registration number — letters + digits,
  conventionally ``CS`` (Company limited by Shares) followed by 9 digits,
  e.g. ``CS123456789``. Other prefixes exist (``CG`` guarantee,
  ``PS`` partnership, ``BN`` business name).
- ``VAT``: GRA-issued TIN — 11 characters starting with ``C`` (company)
  or ``P`` (person) followed by 10 digits, e.g. ``C0001234567``. Newer
  TINs use the Ghana Card PIN (``GHA-NNNNNNNNN-N``) for individuals;
  companies retain the legacy ``C`` format.
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

_RGD_NUMBER_RE = re.compile(r"^(?:CS|CG|PS|BN|EX|CA)[-/]?\d{6,12}$")
_GRA_TIN_RE = re.compile(r"^[CP]\d{10}$")

_GSE_BASE = "https://gse.com.gh"
_RGD_BASE = "https://rgd.gov.gh"
_EREGISTRAR_BASE = "https://eregistrar.rgd.gov.gh"
_GRA_BASE = "https://gra.gov.gh"


class GHAdapter(CountryAdapter):
    country_code = "GH"
    country_name = "Ghana"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        """Probe GSE, then RGD; either reachable = DEGRADED (capabilities gated)."""
        notes_parts: list[str] = []
        gse_ok = await self._probe(_GSE_BASE)
        rgd_ok = await self._probe(_RGD_BASE)
        if not gse_ok:
            notes_parts.append("GSE unreachable")
        if not rgd_ok:
            notes_parts.append("RGD unreachable")

        if not gse_ok and not rgd_ok:
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
                "financials": gse_ok,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "RGD/GRA gated (login + CAPTCHA + paid extracts). "
                "Financials limited to GSE-listed issuers."
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
            "Ghana name search via RGD/eRegistrar requires a logged-in account "
            "and full extracts are paid per document. No free name-search API "
            "is currently available."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                "Ghana supports COMPANY_NUMBER (RGD) or VAT (GRA TIN), got "
                f"{id_type}"
            )
        cleaned = value.strip().upper().replace(" ", "")
        if id_type is IdentifierType.COMPANY_NUMBER and not _RGD_NUMBER_RE.match(
            cleaned
        ):
            raise InvalidIdentifierError(
                "RGD registration number must look like CS123456789 (CS/CG/PS/BN "
                f"+ 6–12 digits), got: {value}"
            )
        if id_type is IdentifierType.VAT and not _GRA_TIN_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"GRA TIN must match [C|P]NNNNNNNNNN (11 chars), got: {value}"
            )
        raise AdapterNotImplementedError(
            "Ghana identifier lookup requires a logged-in eRegistrar session "
            "(COMPANY_NUMBER) or a CAPTCHA-protected GRA request (VAT). "
            "Neither has a free public API."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """Best-effort financials for GSE-listed issuers.

        Free filings on GSE are PDF annual reports posted on each issuer's
        company page. The page is JS-rendered — without a Playwright
        browser pool we cannot deterministically extract real
        ``period_end`` / ``document_url`` per year. Per the no-mock-data
        rule we return an empty list for now; once the PDF + browser
        pipeline lands, this is the natural integration point. Non-listed
        companies have no free filings source at all.
        """
        _ = company_id, years
        return []
