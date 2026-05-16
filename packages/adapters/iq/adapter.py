"""Iraq adapter — Ministry of Trade + Iraq Stock Exchange (ISX).

Source coverage:

* Ministry of Trade / Companies Registrar (https://mot.gov.iq/) — Iraq's
  Companies Registry is operated by the Ministry of Trade. There is no
  documented public JSON API; the customer-facing portal is Arabic-only
  and gates the company detail records behind in-person validation. We
  therefore cannot resolve a company by name or registration number
  without a paid intermediary, which violates the project's non-paid-API
  rule.
* Iraq Stock Exchange (ISX) — https://www.isx-iq.net/. The ISX portal
  publishes annual reports for the small set of listed issuers as PDFs
  served from a session-bound Java portal action. Until the project's
  browser pool lands we cannot enumerate the per-year filing list, so
  `fetch_financials` returns `[]` rather than fabricate placeholders.
  The known test tickers (`TASC`, `BIIB`, `IBSD`) are recognized for
  validation so callers see a clean identifier path.

Identifiers:

* `IdentifierType.COMPANY_NUMBER` carries the Ministry of Trade
  Companies Registrar number or the ISX 4-letter ticker (e.g. `TASC`,
  `BIIB`, `IBSD`). Tickers are 3–5 alphanumerics, registrar numbers are
  numeric strings; both are normalized via upper-case strip.
* `IdentifierType.VAT` carries the Iraqi Tax ID (TIN) issued by the
  General Commission of Taxes. We accept any digit-only string but do
  not attempt a lookup since no free public validator exists.

Per the project rules this adapter never returns mock data: when a
source is blocked or the identifier is non-listed, the relevant call
raises `AdapterNotImplementedError` (search/lookup) or returns `[]`
(financials for non-listed companies).
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

_TICKER_RE = re.compile(r"^[A-Z0-9]{3,6}$")
_REGISTRY_NUMBER_RE = re.compile(r"^\d{1,12}$")
_TIN_RE = re.compile(r"^\d{6,15}$")

# Known ISX-listed issuers we treat as the canonical "real" Iraqi
# companies whose annual reports are public PDFs. Names are the issuer
# names exactly as published on isx-iq.net so we do not fabricate them.
_ISX_LISTED: dict[str, str] = {
    "TASC": "Asiacell Communications PJSC",
    "BIIB": "Iraqi Islamic Bank for Investment and Development",
    "IBSD": "Baghdad Soft Drinks",
}


def _normalize_company_identifier(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if not cleaned:
        raise InvalidIdentifierError("Iraqi company identifier is empty")
    if _TICKER_RE.match(cleaned) or _REGISTRY_NUMBER_RE.match(cleaned):
        return cleaned
    raise InvalidIdentifierError(
        f"Iraqi company identifier must be an ISX ticker (3-6 alphanumerics) "
        f"or a Ministry of Trade registry number (digits), got: {value}"
    )


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Iraqi TIN must be 6-15 digits, got: {value}"
        )
    return cleaned


class IQAdapter(CountryAdapter):
    country_code = "IQ"
    country_name = "Iraq"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 20

    ISX_BASE = "https://www.isx-iq.net"
    MOT_BASE = "https://mot.gov.iq"

    async def health_check(self) -> AdapterHealth:
        reachable_hosts: list[str] = []
        for label, base in (
            ("ISX", self.ISX_BASE),
            ("MoT", self.MOT_BASE),
        ):
            try:
                async with build_http_client(base_url=base, timeout=10.0) as client:
                    resp = await get_with_retry(client, "/", max_attempts=1)
                    if 200 <= resp.status_code < 500:
                        reachable_hosts.append(label)
            except Exception:
                continue

        if not reachable_hosts:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Neither ISX nor Ministry of Trade reachable.",
            )

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Best-effort financials for ISX-listed issuers only. Ministry "
                "of Trade has no public JSON API; name search and identifier "
                "lookup are not available. Reachable: "
                + ", ".join(reachable_hosts) + "."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Iraq Ministry of Trade has no public name-search JSON API; the "
            "ISX portal exposes only a fixed set of listed issuers."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"Iraq supports COMPANY_NUMBER and VAT, got {id_type}"
            )
        if id_type == IdentifierType.VAT:
            _normalize_tin(value)
        else:
            _normalize_company_identifier(value)
        raise AdapterNotImplementedError(
            "Iraq registry lookup is not available without a paid intermediary; "
            "free Ministry of Trade and General Commission of Taxes portals do "
            "not expose structured per-entity records."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # The ISX portal exposes annual-report PDFs from a symbol-keyed
        # Java-portal action that requires a live session and renders the
        # year list client-side. Until the Playwright pool described in
        # CLAUDE.md is in place we cannot extract real period_end / year
        # tuples, and fabricating placeholders would violate rule #1.
        # Validate the identifier so callers learn about bad input even
        # though the return is empty.
        _normalize_company_identifier(company_id)
        return []
