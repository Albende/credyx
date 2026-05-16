"""Bangladesh adapter — RJSC + NBR + DSE.

Sources
-------
- RJSC (Office of the Registrar of Joint Stock Companies and Firms) public
  name search (HTML, partial public):
    http://www.roc.gov.bd:7781/psp/searchEntities.action
- NBR (National Board of Revenue) BIN/e-TIN portal (partial public HTML):
    https://nbr.gov.bd/
- DSE (Dhaka Stock Exchange) — free annual reports for listed companies:
    https://www.dsebd.org/

RJSC's eServices portal is session-bound and CAPTCHA-gated for the full
detail flow; the public name-search route also returns brittle HTML on
a non-standard port (7781) and is regularly blocked by geofencing /
WAF. Per the no-mock-data rule, when the registry is unreachable or
gated we surface `AdapterNotImplementedError` (501) rather than invent
data. The DSE Data Portal is the only reliably free, machine-friendly
source for listed-company annual reports.

Identifiers
-----------
- Registration Number (RJSC) — variable-length numeric ID, typically
  4-7 digits. Primary `COMPANY_NUMBER`.
- BIN (Business Identification Number) — 9- or 13-digit numeric ID
  issued by NBR (also referred to as VAT registration / e-BIN). Mapped
  to `IdentifierType.VAT`.
- TIN (Taxpayer Identification Number) — 12-digit numeric ID issued by
  NBR. Not separately queryable for free; embedded in BIN context for
  many corporate entities.
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
# BIN is 9 digits (legacy) or 13 digits (current e-BIN format issued by NBR).
_BIN_RE = re.compile(r"^\d{9}(\d{4})?$")

# Major DSE-listed companies for which the DSE site hosts annual
# reports. Trading code is the DSE symbol; name is used to confirm
# matches on lookup. Kept small and verifiable — only entries we can
# confirm exist on dsebd.org are included here.
DSE_LISTED: dict[str, dict[str, str]] = {
    "GP": {
        "name": "Grameenphone Ltd.",
        "sector": "Telecommunication",
    },
    "BRACBANK": {
        "name": "BRAC Bank Limited",
        "sector": "Bank",
    },
    "SQURPHARMA": {
        "name": "Square Pharmaceuticals Limited",
        "sector": "Pharmaceuticals & Chemicals",
    },
    "BXPHARMA": {
        "name": "Beximco Pharmaceuticals Limited",
        "sector": "Pharmaceuticals & Chemicals",
    },
    "ROBI": {
        "name": "Robi Axiata Limited",
        "sector": "Telecommunication",
    },
    "BEXIMCO": {
        "name": "Bangladesh Export Import Company Limited",
        "sector": "Miscellaneous",
    },
    "OLYMPIC": {
        "name": "Olympic Industries Limited",
        "sector": "Food & Allied",
    },
    "RENATA": {
        "name": "Renata Limited",
        "sector": "Pharmaceuticals & Chemicals",
    },
}


def normalize_registration_number(value: str) -> str:
    """Strip whitespace and validate the numeric RJSC Registration Number."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _REG_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Bangladesh RJSC Registration Number must be 1-10 digits, "
            f"got {value!r}"
        )
    return cleaned


def normalize_bin(value: str) -> str:
    """Strip whitespace and validate the NBR BIN (9 or 13 digits)."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _BIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Bangladesh BIN must be 9 or 13 digits, got {value!r}"
        )
    return cleaned


class BDAdapter(CountryAdapter):
    country_code = "BD"
    country_name = "Bangladesh"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    # RJSC's public search runs on a non-standard port; we keep it explicit
    # so a future ops change (e.g. migration to https) is a one-line edit.
    RJSC_BASE = "http://www.roc.gov.bd:7781"
    RJSC_SEARCH_PATH = "/psp/searchEntities.action"
    NBR_BASE = "https://nbr.gov.bd"
    DSE_BASE = "https://www.dsebd.org"

    def _client(self, base_url: str | None = None) -> httpx.AsyncClient:
        # RJSC and NBR both reject default httpx UA on occasion; pass a
        # browser-style Accept header. UTF-8 covers Bengali text in any
        # parsed labels/values.
        return build_http_client(
            base_url=base_url or self.RJSC_BASE,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Charset": "utf-8",
            },
        )

    async def health_check(self) -> AdapterHealth:
        # DSE is the most reliable upstream; probe it as the canonical signal.
        try:
            async with self._client(base_url=self.DSE_BASE) as client:
                resp = await get_with_retry(client, "/", max_attempts=2)
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
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
                "RJSC name search is brittle (port 7781, CAPTCHA on detail). "
                "Listed-company lookups use DSE Data Portal; unlisted RJSC "
                "filings require paid per-document downloads."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # Surface DSE-listed companies that match — these are the only
        # entities we can honestly return without driving the RJSC
        # CAPTCHA / session flow.
        needle = name.strip().lower()
        if not needle:
            return []
        matches: list[CompanyMatch] = []
        for symbol, info in DSE_LISTED.items():
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
                                label="DSE Symbol",
                            )
                        ],
                        status="listed",
                        source_url=f"{self.DSE_BASE}/displayCompany.php?name={symbol}",
                    )
                )
                if len(matches) >= limit:
                    break
        if matches:
            return matches
        # No listed match and the RJSC name-search route is gated; raise per
        # contract instead of returning fake or empty-but-misleading results.
        raise AdapterNotImplementedError(
            "RJSC name search (roc.gov.bd:7781) is CAPTCHA + session gated; "
            "only DSE-listed companies can be returned without auth. See "
            "docs/countries/bd.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            bin_value = normalize_bin(value)
            # NBR's online BIN/e-TIN inquiry requires CAPTCHA + login; no
            # free programmatic lookup. Surface 501 honestly.
            raise AdapterNotImplementedError(
                f"NBR BIN inquiry ({bin_value}) is CAPTCHA + login gated at "
                "nbr.gov.bd. Use RJSC Registration Number, or DSE symbol "
                "for listed companies."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"BD supports COMPANY_NUMBER (RJSC Registration Number) and "
                f"VAT (BIN), got {id_type}"
            )

        raw = value.strip()
        # DSE symbols (e.g. "GP", "BRACBANK") are short alpha tokens; route
        # them to the listed-company path which is the only free working
        # source.
        if raw.upper() in DSE_LISTED:
            return self._details_from_dse(raw.upper())

        # Otherwise treat the value as a numeric RJSC Registration Number.
        reg = normalize_registration_number(raw)
        async with self._client() as client:
            try:
                resp = await get_with_retry(
                    client,
                    self.RJSC_SEARCH_PATH,
                    params={"regNo": reg},
                    max_attempts=2,
                )
            except httpx.HTTPError as exc:
                raise AdapterNotImplementedError(
                    "RJSC company detail by Registration Number requires the "
                    f"eServices session flow; not available for free ({exc})."
                )
            if resp.status_code >= 500:
                resp.raise_for_status()
        # Even when the search endpoint answers, the per-company detail data
        # lives behind the eServices session + CAPTCHA. We cannot honestly
        # extract company facts from a public URL alone.
        raise AdapterNotImplementedError(
            f"RJSC Registration Number {reg} lookup needs the eServices "
            "authenticated session. Free MVP supports DSE-listed companies "
            "only via DSE symbol."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        symbol = company_id.strip().upper()
        if symbol not in DSE_LISTED:
            # Unlisted Bangladeshi filings sit behind RJSC eServices document
            # downloads (paid per-document). [] is the honest answer.
            return []

        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        # DSE indexes annual reports under /displayCompany.php?name={SYMBOL}
        # with per-year PDF URLs generated server-side after the listing
        # page renders. We surface one navigation pointer per recent FY,
        # source_url set to the listing page — no fabricated numbers.
        for year in range(datetime.utcnow().year - 1, cutoff_year - 1, -1):
            filings.append(
                FinancialFiling(
                    company_id=symbol,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=None,
                    currency="BDT",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=f"{self.DSE_BASE}/displayCompany.php?name={symbol}",
                )
            )
        return filings

    def _details_from_dse(self, symbol: str) -> CompanyDetails:
        info = DSE_LISTED[symbol]
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
                    label="DSE Symbol",
                ),
            ],
            raw={"dse_symbol": symbol, "sector": info["sector"]},
            source_url=f"{self.DSE_BASE}/displayCompany.php?name={symbol}",
            capital_currency="BDT",
        )


__all__ = [
    "BDAdapter",
    "normalize_registration_number",
    "normalize_bin",
    "DSE_LISTED",
]
