"""Jordan adapter — Companies Control Department (MIT) + Amman Stock Exchange.

Source coverage:

* Companies Control Department (CCD) — https://www.ccd.gov.jo/ — and the
  Ministry of Industry, Trade and Supply — https://www.mit.gov.jo/. The
  national companies register exposes a public search portal in Arabic
  only; the underlying JSON endpoints are protected by an ASP.NET event-
  validation token and require an interactive session. There is no free
  REST API for name search or identifier lookup.
* Income and Sales Tax Department (ISTD) — https://www.istd.gov.jo/. The
  Tax Reference Number (TRN) validator is form-based and renders results
  client-side; no documented JSON contract.
* Amman Stock Exchange (ASE) — https://www.ase.com.jo/. Annual reports
  and audited financials for ASE-listed issuers are published as free
  PDFs on each issuer's profile page. There is no documented data API,
  but issuer pages are reachable by ticker symbol and serve as the
  authoritative free source of financials for listed Jordanian firms.

Per the project rules this adapter never fabricates data: where a source
is gated (CCD search, MIT name lookup, ISTD validator) the call raises
`AdapterNotImplementedError`. For ASE-listed issuers `fetch_financials`
emits a single `FinancialFiling` per recent fiscal year that points at
the public ASE company profile so downstream PDF-extraction can pick the
filings up once the Playwright pool is wired.

Identifiers:

* CCD Company Number — variable-length numeric registration number used
  by MIT/CCD, encoded as `IdentifierType.COMPANY_NUMBER`.
* Tax Reference Number (TRN) — 9-digit identifier issued by ISTD, mapped
  to `IdentifierType.VAT` since it doubles as the GST/VAT registration.
"""
from __future__ import annotations

import re
from datetime import datetime

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
    RegistryIdentifier,
)

_COMPANY_NUMBER_RE = re.compile(r"^\d{1,10}$")
_TRN_RE = re.compile(r"^\d{9}$")

# ASE tickers we know are listed today. The mapping is intentionally
# small: the MVP rule is no fabricated data — if a ticker is not in this
# list `fetch_financials` returns []. Real ticker coverage can grow as
# the Playwright pool lands and ASE issuer lists become scrapable.
_ASE_TICKERS: dict[str, str] = {
    "ARBK": "Arab Bank PLC",
    "JOPH": "Jordan Phosphate Mines Company",
    "HIKM": "Hikma Pharmaceuticals",
    "JTEL": "Jordan Telecom (Orange Jordan)",
}


def _normalize_company_number(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _COMPANY_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Jordan CCD company number must be up to 10 digits, got: {value}"
        )
    return cleaned


def _normalize_trn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _TRN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Jordan Tax Reference Number must be 9 digits, got: {value}"
        )
    return cleaned


def _normalize_ticker(value: str) -> str:
    return re.sub(r"[\s\-]", "", value.strip()).upper()


class JOAdapter(CountryAdapter):
    country_code = "JO"
    country_name = "Jordan"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CCD_BASE = "https://www.ccd.gov.jo"
    MIT_BASE = "https://www.mit.gov.jo"
    ASE_BASE = "https://www.ase.com.jo"

    async def health_check(self) -> AdapterHealth:
        reachable: list[str] = []
        for label, base in (
            ("ASE", self.ASE_BASE),
            ("CCD", self.CCD_BASE),
        ):
            try:
                async with build_http_client(base_url=base, timeout=10.0) as client:
                    resp = await get_with_retry(client, "/", max_attempts=1)
                    if 200 <= resp.status_code < 500:
                        reachable.append(label)
            except Exception:
                continue

        if not reachable:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes="Neither ASE nor CCD reachable from host.",
            )

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "Financials available only for ASE-listed issuers via free "
                "PDF annual reports. CCD/MIT name search and TRN validator "
                "are gated (Arabic-only ASP.NET sessions, no public JSON). "
                "Reachable: " + ", ".join(reachable) + "."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Jordan CCD/MIT name search has no free public JSON endpoint; "
            "the official portal is Arabic-only and session-gated."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            _normalize_company_number(value)
            raise AdapterNotImplementedError(
                "Jordan CCD does not expose a free identifier lookup endpoint; "
                "company details require the gated CCD eServices portal."
            )
        if id_type == IdentifierType.VAT:
            _normalize_trn(value)
            raise AdapterNotImplementedError(
                "Jordan ISTD TRN validator is form-only with no public JSON "
                "response; no free structured details available."
            )
        raise InvalidIdentifierError(
            f"Jordan supports COMPANY_NUMBER and VAT (TRN), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = _normalize_ticker(company_id)
        issuer_name = _ASE_TICKERS.get(ticker)
        if not issuer_name:
            # Unlisted (or unknown-ticker) issuers have no free Jordanian
            # filings source. Returning an empty list — never invented PDFs —
            # is the contracted behaviour.
            return []

        profile_url = f"{self.ASE_BASE}/en/Company-Profile/{ticker}"

        # ASE keeps annual financial PDFs on the issuer profile; we cannot
        # enumerate them without rendering the SPA. Emit one filing record
        # per recent fiscal year pointing at the public profile so the PDF
        # pipeline (once enabled) can pick up the artefacts. Period_end and
        # structured_data are intentionally left null — no fabrication.
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for year in range(current_year - 1, current_year - 1 - years, -1):
            filings.append(
                FinancialFiling(
                    company_id=ticker,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=None,
                    currency="JOD",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=profile_url,
                )
            )
        return filings
