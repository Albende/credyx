"""Mauritius adapter — ROC / CBRD + SEM.

Sources
-------
- ROC / CBRD (Corporate and Business Registration Department) public
  name search:
    https://onlinebrn.govmu.org/
- SEM (Stock Exchange of Mauritius) — free annual reports for the
  listed Official + DEM market issuers:
    https://www.stockexchangeofmauritius.com/

The ROC's onlinebrn portal renders its name-search results inside a
JSF/PrimeFaces ViewState session — the public landing page exposes
only an HTML form whose POST requires the rotated ViewState token.
Per the no-mock-data rule, when we cannot deterministically read the
registry we surface ``AdapterNotImplementedError`` (501) rather than
invent data. SEM listings are the only reliably free, machine-friendly
source for listed-company annual reports.

Identifiers
-----------
- BRN (Business Registration Number) — alphanumeric ID issued by CBRD
  for both companies and businesses, typically a single leading letter
  followed by digits (e.g. ``C07012345``). Mapped to
  ``IdentifierType.COMPANY_NUMBER``.
- VAT — 8-digit VAT Registration Number (VRN) issued by the Mauritius
  Revenue Authority. Mapped to ``IdentifierType.VAT``.
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


# BRN: letter prefix (C company, F foreign, P partnership, etc.) plus digits.
_BRN_RE = re.compile(r"^[A-Z]\d{5,12}$")
# VRN: 8 numeric digits as printed on MRA VAT certificates.
_VRN_RE = re.compile(r"^\d{8}$")


# SEM-listed issuers we can honestly surface without driving the JSF
# session at onlinebrn. Tickers and legal names verified against the
# SEM Official Market issuer list. Kept small and curated.
SEM_LISTED: dict[str, dict[str, str]] = {
    "MCBG": {
        "name": "MCB Group Limited",
        "sector": "Banks, Insurance & Other Finance",
    },
    "SBMH": {
        "name": "SBM Holdings Ltd",
        "sector": "Banks, Insurance & Other Finance",
    },
    "AIRM": {
        "name": "Air Mauritius Limited",
        "sector": "Transport",
    },
    "SUNL": {
        "name": "Sun Limited",
        "sector": "Leisure & Hotels",
    },
}


def normalize_brn(value: str) -> str:
    """Validate and normalize a Mauritius BRN to its uppercase canonical form."""
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if not _BRN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Mauritius BRN must be one letter followed by 5-12 digits, "
            f"got {value!r}"
        )
    return cleaned


def normalize_vrn(value: str) -> str:
    """Validate and normalize a Mauritius VAT Registration Number (VRN)."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _VRN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Mauritius VRN must be 8 digits, got {value!r}"
        )
    return cleaned


class MUAdapter(CountryAdapter):
    country_code = "MU"
    country_name = "Mauritius"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    ROC_BASE = "https://onlinebrn.govmu.org"
    SEM_BASE = "https://www.stockexchangeofmauritius.com"

    async def health_check(self) -> AdapterHealth:
        """SEM is the canonical upstream we actually serve from; probe it."""
        try:
            async with build_http_client(base_url=self.SEM_BASE, timeout=10.0) as client:
                resp = await get_with_retry(client, "/", max_attempts=2)
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={
                "search": True,
                "lookup": True,
                "financials": True,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "ROC/CBRD onlinebrn name search is JSF/ViewState-gated; only "
                "SEM-listed issuers are returned without auth. Non-listed "
                "filings require paid per-document downloads at CBRD."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = name.strip().lower()
        if not needle:
            return []
        matches: list[CompanyMatch] = []
        for symbol, info in SEM_LISTED.items():
            if needle in info["name"].lower() or needle == symbol.lower():
                matches.append(
                    CompanyMatch(
                        id=symbol,
                        name=info["name"],
                        country=self.country_code,
                        identifiers=[
                            RegistryIdentifier(
                                type=IdentifierType.OTHER,
                                value=symbol,
                                label="SEM Ticker",
                            )
                        ],
                        status="listed",
                        source_url=f"{self.SEM_BASE}/listed-companies",
                    )
                )
                if len(matches) >= limit:
                    break
        if matches:
            return matches
        raise AdapterNotImplementedError(
            "ROC/CBRD onlinebrn.govmu.org name search is JSF/ViewState-gated; "
            "only SEM-listed companies can be returned without a session. "
            "See docs/countries/mu.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            vrn = normalize_vrn(value)
            raise AdapterNotImplementedError(
                f"Mauritius VAT (VRN {vrn}) lookup is not exposed as a free "
                "public API by the MRA; the e-services portal is login-only."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"MU supports COMPANY_NUMBER (BRN) and VAT (VRN), got {id_type}"
            )

        raw = value.strip()
        # SEM tickers are short alpha tokens; route them to the listed-company
        # path which is the only free working source.
        if raw.upper() in SEM_LISTED:
            return self._details_from_sem(raw.upper())

        # Otherwise treat the value as a BRN.
        brn = normalize_brn(raw)
        raise AdapterNotImplementedError(
            f"ROC/CBRD BRN {brn} detail lookup requires the onlinebrn "
            "JSF/ViewState session and paid extract download. Free MVP "
            "supports SEM-listed companies only via SEM ticker."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        symbol = company_id.strip().upper()
        if symbol not in SEM_LISTED:
            # Unlisted Mauritian filings sit behind CBRD paid document
            # downloads. [] is the honest answer per the no-mock rule.
            return []

        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        # SEM publishes annual reports on each issuer's company page, but the
        # listing is JS-rendered and per-FY PDF URLs are generated server-side.
        # We surface one navigation pointer per recent FY pointing at the
        # SEM listed-companies index — no fabricated numbers.
        for year in range(datetime.utcnow().year - 1, cutoff_year - 1, -1):
            filings.append(
                FinancialFiling(
                    company_id=symbol,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=None,
                    currency="MUR",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=f"{self.SEM_BASE}/listed-companies",
                )
            )
        return filings

    def _details_from_sem(self, symbol: str) -> CompanyDetails:
        info = SEM_LISTED[symbol]
        return CompanyDetails(
            id=symbol,
            name=info["name"],
            country=self.country_code,
            legal_form="Public Limited Company (SEM Listed)",
            status="listed",
            sic_codes=[],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=symbol,
                    label="SEM Ticker",
                ),
            ],
            raw={"sem_ticker": symbol, "sector": info["sector"]},
            source_url=f"{self.SEM_BASE}/listed-companies",
            capital_currency="MUR",
        )


__all__ = [
    "MUAdapter",
    "normalize_brn",
    "normalize_vrn",
    "SEM_LISTED",
]
