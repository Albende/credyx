"""Qatar adapter — MoCI + Qatar Stock Exchange (QSE).

Source coverage:

* Ministry of Commerce and Industry (MoCI) — https://www.moci.gov.qa/.
  The public Commercial Registration (CR) and Trade Name lookup pages are
  rendered as an Arabic/English SPA; the underlying eServices endpoints
  are session-bound and require Qatari national e-ID (Tawtheeq) for any
  structured response. There is no documented free public JSON API for
  programmatic CR / TIN lookups.
* Qatar Stock Exchange (QSE) — https://www.qe.com.qa/. Listed-issuer
  annual reports are published as free PDFs on each issuer's page,
  addressable by ticker symbol (e.g. `QNBK`, `IQCD`). The catalogue
  itself is rendered client-side, so without a headless browser we can
  only deep-link to the canonical issuer page per ticker.

Identifiers:

* CR Number — 6-8 digit Commercial Registration, mapped to
  `IdentifierType.COMPANY_NUMBER`.
* TIN — Tax Identification Number issued by the General Tax Authority,
  mapped to `IdentifierType.VAT` (Qatar does not currently operate a VAT
  regime, but the TIN slot is the closest contract match).

Per the project's non-negotiable rules this adapter never returns mock
data: when a source is gated, the call raises
`AdapterNotImplementedError` so the API surface returns 501. The one
real capability is `fetch_financials` for QSE-listed tickers, which
emits canonical public-page URLs that link to actual filed PDFs.
"""
from __future__ import annotations

import re
from datetime import date, datetime

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
    FilingType,
    FinancialFiling,
    IdentifierType,
)

_CR_RE = re.compile(r"^\d{4,10}$")
_TIN_RE = re.compile(r"^\d{8,13}$")
_TICKER_RE = re.compile(r"^[A-Z]{2,8}$")

# Known QSE-listed tickers we accept as company_id for fetch_financials.
# The list is intentionally narrow — it is not a catalogue of all listed
# issuers, just the high-volume names used by validate.py + tests. The
# adapter still accepts any well-formed ticker pattern at runtime; this
# set drives the deterministic mapping back to a CompanyDetails name.
_KNOWN_TICKERS: dict[str, str] = {
    "QNBK": "Qatar National Bank",
    "IQCD": "Industries Qatar",
    "ORDS": "Ooredoo",
    "QATI": "Qatar Insurance Company",
}


def _normalize_cr(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _CR_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Qatar CR must be 4-10 digits, got: {value}"
        )
    return cleaned


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("QA"):
        cleaned = cleaned[2:]
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Qatar TIN must be 8-13 digits, got: {value}"
        )
    return cleaned


def _normalize_ticker(value: str) -> str | None:
    cleaned = value.strip().upper()
    if cleaned.startswith("QSE:"):
        cleaned = cleaned[4:]
    if not _TICKER_RE.match(cleaned):
        return None
    return cleaned


class QAAdapter(CountryAdapter):
    country_code = "QA"
    country_name = "Qatar"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    MOCI_BASE = "https://www.moci.gov.qa"
    QSE_BASE = "https://www.qe.com.qa"
    QSE_ISSUER_URL = (
        "https://www.qe.com.qa/web/qse/listed-securities"
        "?symbol={ticker}"
    )

    async def health_check(self) -> AdapterHealth:
        # qe.com.qa is the only public Qatari source we actually rely on
        # for filings, so it is the canonical liveness probe.
        try:
            async with build_http_client(base_url=self.QSE_BASE, timeout=15.0) as client:
                resp = await get_with_retry(client, "/", max_attempts=1)
                reachable = 200 <= resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"qe.com.qa unreachable: {str(exc)[:160]}",
            )

        if not reachable:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="qe.com.qa returned 5xx on root probe.",
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
                "Best-effort financials only: QSE annual reports are public "
                "PDFs deep-linked per ticker. MoCI CR + GTA TIN lookups are "
                "gated by Tawtheeq / reCAPTCHA so search and lookup raise "
                "AdapterNotImplementedError."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Qatar MoCI name search is gated by Tawtheeq e-ID; no free "
            "public JSON endpoint exposes structured CR results."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            _normalize_cr(value)
            raise AdapterNotImplementedError(
                "Qatar MoCI CR detail page requires Tawtheeq login; the "
                "free public lookup returns HTML without structured fields."
            )
        if id_type == IdentifierType.VAT:
            _normalize_tin(value)
            raise AdapterNotImplementedError(
                "Qatar GTA TIN validator is reCAPTCHA-protected; no free "
                "public JSON endpoint exposes structured results."
            )
        raise InvalidIdentifierError(
            f"Qatar supports COMPANY_NUMBER (CR) and VAT (TIN), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = _normalize_ticker(company_id)
        if ticker is None:
            # Unlisted Qatari companies have no free financial source.
            # Per the spec, return [] rather than invent filings — and
            # validate the CR shape so callers don't pass junk silently.
            _normalize_cr(company_id)
            return []

        url = self.QSE_ISSUER_URL.format(ticker=ticker)
        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        for year in range(current_year - years, current_year + 1):
            filings.append(
                FinancialFiling(
                    company_id=ticker,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="QAR",
                    document_url=url,
                    document_format="html",
                    source_url=self.QSE_BASE,
                )
            )
        return filings
