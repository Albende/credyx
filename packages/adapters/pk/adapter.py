"""Pakistan adapter — SECP + FBR + PSX.

Sources
-------
- SECP eServices public name search (HTML):
    https://www.secp.gov.pk/data-and-statistics/eservices/
- SECP company detail pages (HTML, partial public):
    https://www.secp.gov.pk/
- FBR NTN online verification (partial public HTML):
    https://e.fbr.gov.pk/
- PSX Data Portal — annual reports for listed companies (free):
    https://dps.psx.com.pk/

SECP's eServices portal is session + CAPTCHA + ViewState gated; there is
no honest free way to drive the name search programmatically. Per the
no-mock-data rule we surface that as `AdapterNotImplementedError` (501).
Direct company-detail URLs by Incorporation Number are partially public
and can be scraped when SECP exposes them; if the registry blocks the
request (CAPTCHA, geoblock) we raise instead of inventing data.

Identifiers
-----------
- Incorporation Number — variable format, typically a 7-digit numeric ID
  optionally zero-padded (e.g. `0012345`). Primary.
- NTN (National Tax Number) — 7- or 8-digit numeric ID issued by FBR;
  mapped to `IdentifierType.VAT`.
"""
from __future__ import annotations

import re

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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)


_INC_NUMBER_RE = re.compile(r"^\d{1,10}$")
_NTN_RE = re.compile(r"^\d{7,8}(-\d)?$")

# Major PSX-listed companies for which the Data Portal hosts annual
# reports. Symbol is the PSX trading symbol; name is used to confirm
# matches on lookup. The map is intentionally small — only entries we
# can verify exist on dps.psx.com.pk are kept here.
PSX_LISTED: dict[str, dict[str, str]] = {
    "HBL": {"name": "Habib Bank Limited", "sector": "Commercial Banks"},
    "ENGRO": {"name": "Engro Corporation Limited", "sector": "Chemicals"},
    "PPL": {"name": "Pakistan Petroleum Limited", "sector": "Oil & Gas Exploration"},
    "LUCK": {"name": "Lucky Cement Limited", "sector": "Cement"},
    "OGDC": {"name": "Oil & Gas Development Company Limited", "sector": "Oil & Gas Exploration"},
    "MCB": {"name": "MCB Bank Limited", "sector": "Commercial Banks"},
    "UBL": {"name": "United Bank Limited", "sector": "Commercial Banks"},
    "FFC": {"name": "Fauji Fertilizer Company Limited", "sector": "Fertilizer"},
}


def normalize_incorporation_number(value: str) -> str:
    """Strip whitespace and validate the numeric Incorporation Number."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _INC_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Pakistan Incorporation Number must be 1-10 digits, got {value!r}"
        )
    return cleaned.zfill(7)


def normalize_ntn(value: str) -> str:
    """Strip whitespace and validate the FBR NTN."""
    cleaned = value.strip().replace(" ", "")
    if not _NTN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Pakistan NTN must be 7-8 digits (optional -check), got {value!r}"
        )
    return cleaned


class PKAdapter(CountryAdapter):
    country_code = "PK"
    country_name = "Pakistan"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    SECP_BASE = "https://www.secp.gov.pk"
    FBR_BASE = "https://e.fbr.gov.pk"
    PSX_BASE = "https://dps.psx.com.pk"

    def _client(self, base_url: str | None = None) -> httpx.AsyncClient:
        return build_http_client(
            base_url=base_url or self.SECP_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
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
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search disabled (SECP eServices is CAPTCHA + ViewState "
                "gated). Lookup is limited to PSX-listed companies via the "
                "PSX Data Portal; SECP filing scrape is not free for unlisted."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # Surface listed companies that match — these are the only entities
        # we can honestly return without driving the SECP CAPTCHA flow.
        needle = name.strip().lower()
        if not needle:
            return []
        matches: list[CompanyMatch] = []
        for symbol, info in PSX_LISTED.items():
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
                                label="PSX Symbol",
                            )
                        ],
                        status="listed",
                        source_url=f"{self.PSX_BASE}/company/{symbol}",
                    )
                )
                if len(matches) >= limit:
                    break
        if matches:
            return matches
        # No listed match and the SECP name-search route is gated; raise per
        # contract instead of returning fake or empty-but-misleading results.
        raise AdapterNotImplementedError(
            "SECP eServices name search is CAPTCHA + ViewState gated; only "
            "PSX-listed companies can be returned without auth. See "
            "docs/countries/pk.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            ntn = normalize_ntn(value)
            # FBR's Online NTN/STRN Inquiry requires CAPTCHA + ViewState; no
            # free programmatic lookup. Surface 501 honestly.
            raise AdapterNotImplementedError(
                f"FBR NTN inquiry ({ntn}) is CAPTCHA-gated at e.fbr.gov.pk. "
                "Use Incorporation Number via SECP, or PSX symbol for listed."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"PK supports COMPANY_NUMBER (Incorporation Number) and VAT "
                f"(NTN), got {id_type}"
            )

        raw = value.strip()
        # PSX symbols (e.g. "HBL") are short alpha tokens; route them to the
        # listed-company path which is the only free working source.
        if raw.upper() in PSX_LISTED:
            return self._details_from_psx(raw.upper())

        # Otherwise treat the value as a numeric Incorporation Number.
        inc = normalize_incorporation_number(raw)
        async with self._client() as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/",
                    params={"q": inc},
                    max_attempts=2,
                )
            except httpx.HTTPError as exc:
                raise AdapterNotImplementedError(
                    f"SECP company detail by Incorporation Number requires the "
                    f"eServices session flow; not available for free ({exc})."
                )
            if resp.status_code >= 500:
                resp.raise_for_status()
        # Even when SECP's homepage answers, the per-company detail data lives
        # behind the eServices session; we cannot honestly extract company
        # facts from a public URL. Surface 501 rather than parse mock data.
        raise AdapterNotImplementedError(
            f"SECP Incorporation Number {inc} lookup needs the eServices "
            "authenticated session. Free MVP supports PSX-listed companies "
            "only via PSX symbol."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Per the no-mock-data rule, we never emit per-year filings without
        # confirming the year exists. Discovering PSX per-year PDFs requires
        # the Data Portal session/JS; that lives in Phase 2 behind the
        # browser pool. Until then we return [] honestly — `CompanyDetails`
        # already exposes the PSX financial-reports listing URL for listed
        # companies, which is the navigation pointer the UI needs.
        _ = company_id, years
        return []

    def _details_from_psx(self, symbol: str) -> CompanyDetails:
        info = PSX_LISTED[symbol]
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
                    label="PSX Symbol",
                ),
            ],
            raw={"psx_symbol": symbol, "sector": info["sector"]},
            source_url=f"{self.PSX_BASE}/company/{symbol}",
            capital_currency="PKR",
        )


__all__ = [
    "PKAdapter",
    "normalize_incorporation_number",
    "normalize_ntn",
    "PSX_LISTED",
]
