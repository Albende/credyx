"""Nepal adapter — OCR + IRD + NEPSE.

Sources
-------
- OCR (Office of the Company Registrar) public name search (HTML, partial
  public): https://ocr.gov.np/
- IRD (Inland Revenue Department) PAN validator (CAPTCHA-gated, web-only):
  https://ird.gov.np/
- NEPSE (Nepal Stock Exchange) — free annual reports for listed companies:
  https://www.nepalstock.com/

OCR's public portal exposes a search form but every detail page is gated
behind a session + JavaScript-rendered table; the IRD PAN validator
likewise requires a captcha. Per the no-mock-data rule, when the
registry is unreachable or gated we surface `AdapterNotImplementedError`
(501) rather than invent data. NEPSE is the only reliably free,
machine-friendly source for listed-company annual reports.

Identifiers
-----------
- Company Registration Number (OCR) — variable-length numeric ID. Mapped
  to `IdentifierType.COMPANY_NUMBER` and treated as the primary id.
- PAN (Permanent Account Number) — 9-digit numeric tax ID issued by IRD,
  also used as VAT-registration number for VAT-registered businesses.
  Mapped to `IdentifierType.VAT`.

UTF-8 throughout because company names commonly contain Devanagari text
(e.g. "नेपाल टेलिकम").
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx

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


_REG_NUMBER_RE = re.compile(r"^\d{1,10}$")
# Nepal PAN is a 9-digit number issued by IRD; the same number functions
# as the VAT registration for VAT-registered taxpayers.
_PAN_RE = re.compile(r"^\d{9}$")


# NEPSE-listed companies we can verifiably link to on nepalstock.com. Kept
# intentionally small — every entry must be a real, currently listed
# symbol so the source_url resolves. Trading "symbol" is the NEPSE
# ticker; "name" is used to confirm matches on lookup.
NEPSE_LISTED: dict[str, dict[str, str]] = {
    "NABIL": {
        "name": "Nabil Bank Limited",
        "sector": "Commercial Banks",
    },
    "NTC": {
        "name": "Nepal Telecom",
        "sector": "Telecommunication",
    },
    "NIMB": {
        "name": "Nepal Investment Mega Bank Limited",
        "sector": "Commercial Banks",
    },
    "SCB": {
        "name": "Standard Chartered Bank Nepal Limited",
        "sector": "Commercial Banks",
    },
    "NICA": {
        "name": "NIC Asia Bank Limited",
        "sector": "Commercial Banks",
    },
    "EBL": {
        "name": "Everest Bank Limited",
        "sector": "Commercial Banks",
    },
    "HBL": {
        "name": "Himalayan Bank Limited",
        "sector": "Commercial Banks",
    },
    "NLIC": {
        "name": "Nepal Life Insurance Company Limited",
        "sector": "Life Insurance",
    },
}


def normalize_registration_number(value: str) -> str:
    """Strip whitespace and validate the OCR Company Registration Number."""
    cleaned = value.strip().replace(" ", "").replace("-", "").replace("/", "")
    if not _REG_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Nepal OCR Registration Number must be 1-10 digits, got {value!r}"
        )
    return cleaned


def normalize_pan(value: str) -> str:
    """Strip whitespace and validate the IRD PAN (9 digits)."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _PAN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Nepal PAN must be 9 digits, got {value!r}"
        )
    return cleaned


class NPAdapter(CountryAdapter):
    country_code = "NP"
    country_name = "Nepal"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    OCR_BASE = "https://ocr.gov.np"
    IRD_BASE = "https://ird.gov.np"
    NEPSE_BASE = "https://www.nepalstock.com"

    def _client(self, base_url: str | None = None) -> httpx.AsyncClient:
        # Explicit UTF-8 + browser-style Accept; OCR and NEPSE both serve
        # mixed English/Devanagari content and reject minimal UAs.
        return build_http_client(
            base_url=base_url or self.NEPSE_BASE,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Charset": "utf-8",
            },
        )

    async def health_check(self) -> AdapterHealth:
        # NEPSE is the most reliable upstream; probe it as the canonical
        # signal. Fall back to OCR if NEPSE is unreachable so the user
        # gets useful information either way.
        try:
            async with self._client(base_url=self.NEPSE_BASE) as client:
                resp = await get_with_retry(client, "/", max_attempts=2)
                ok = resp.status_code < 500
        except Exception:
            try:
                async with self._client(base_url=self.OCR_BASE) as client:
                    resp = await get_with_retry(client, "/", max_attempts=2)
                    ok = resp.status_code < 500
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
                    rate_limit_per_minute=self.rate_limit_per_minute,
                    notes=str(exc)[:200],
                )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "OCR name search is JS/session-rendered; IRD PAN validator "
                "is CAPTCHA-gated. Listed-company lookups use NEPSE; "
                "unlisted OCR filings require an authenticated session."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # Surface NEPSE-listed companies that match — these are the only
        # entities we can honestly return without driving the OCR session
        # / JS-render flow.
        needle = name.strip().lower()
        if not needle:
            return []
        matches: list[CompanyMatch] = []
        for symbol, info in NEPSE_LISTED.items():
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
                                label="NEPSE Symbol",
                            )
                        ],
                        status="listed",
                        source_url=(
                            f"{self.NEPSE_BASE}/company/detail/{symbol}"
                        ),
                    )
                )
                if len(matches) >= limit:
                    break
        if matches:
            return matches
        raise AdapterNotImplementedError(
            "OCR name search (ocr.gov.np) is JS/session-rendered and not "
            "callable without a browser pool. Only NEPSE-listed companies "
            "can be returned today. See docs/countries/np.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            pan = normalize_pan(value)
            raise AdapterNotImplementedError(
                f"IRD PAN inquiry ({pan}) is CAPTCHA-gated at ird.gov.np. "
                "Use OCR Registration Number, or NEPSE symbol for listed "
                "companies."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                "NP supports COMPANY_NUMBER (OCR Registration Number) and "
                f"VAT (PAN), got {id_type}"
            )

        raw = value.strip()
        # NEPSE symbols are short alpha tokens (NABIL, NTC, NIMB, …); route
        # them to the listed-company path which is the only free working
        # source.
        if raw.upper() in NEPSE_LISTED:
            return self._details_from_nepse(raw.upper())

        # Otherwise treat the value as a numeric OCR Registration Number.
        reg = normalize_registration_number(raw)
        async with self._client(base_url=self.OCR_BASE) as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/",
                    params={"q": reg},
                    max_attempts=2,
                )
            except httpx.HTTPError as exc:
                raise AdapterNotImplementedError(
                    "OCR company detail by Registration Number requires the "
                    f"authenticated portal session; not available for free "
                    f"({exc})."
                )
            if resp.status_code >= 500:
                resp.raise_for_status()
        # Even when the search endpoint answers, per-company detail data
        # lives behind a JS-rendered table + session. We cannot honestly
        # extract company facts from a public URL alone.
        raise AdapterNotImplementedError(
            f"OCR Registration Number {reg} lookup needs the ocr.gov.np "
            "authenticated session. Free MVP supports NEPSE-listed "
            "companies only via NEPSE symbol."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        symbol = company_id.strip().upper()
        if symbol not in NEPSE_LISTED:
            # Unlisted Nepali filings sit behind OCR's authenticated portal
            # (free in principle but session/JS-gated). [] is the honest
            # answer.
            return []

        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        # NEPSE publishes annual reports on the per-company page under
        # /company/detail/{SYMBOL}, with per-year PDF URLs generated
        # server-side after the page renders. Surface one navigation
        # pointer per recent FY, source_url set to the listing page —
        # no fabricated numbers.
        for year in range(datetime.utcnow().year - 1, cutoff_year - 1, -1):
            filings.append(
                FinancialFiling(
                    company_id=symbol,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=None,
                    currency="NPR",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=f"{self.NEPSE_BASE}/company/detail/{symbol}",
                )
            )
        return filings

    def _details_from_nepse(self, symbol: str) -> CompanyDetails:
        info = NEPSE_LISTED[symbol]
        return CompanyDetails(
            id=symbol,
            name=info["name"],
            country=self.country_code,
            legal_form="Public Limited Company (Listed)",
            status="listed",
            sic_codes=[],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=symbol,
                    label="NEPSE Symbol",
                ),
            ],
            raw={"nepse_symbol": symbol, "sector": info["sector"]},
            source_url=f"{self.NEPSE_BASE}/company/detail/{symbol}",
            capital_currency="NPR",
        )


__all__ = [
    "NPAdapter",
    "normalize_registration_number",
    "normalize_pan",
    "NEPSE_LISTED",
]
