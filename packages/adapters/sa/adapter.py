"""Saudi Arabia adapter — GLEIF registry + Saudi Exchange (Tadawul).

Coverage, all free and key-less:

* **Registry (search + identifier lookup) — GLEIF.** The Global LEI index
  stores each Saudi legal entity's Commercial Registration number in
  ``entity.registeredAs`` (Saudi Ministry of Commerce, RA000513), so a CR
  resolves to a real structured record (legal name, LEI, address, status)
  and a fulltext name search matches Arabic legal names through their
  transliterated forms. Both endpoints are public JSON:API.
* **Financials — Saudi Exchange main-market company profile.** TASI-listed
  issuers publish server-rendered annual balance-sheet / income /
  cash-flow tables. The portal sits behind Akamai and a rotating portal
  token, so we harvest the embedded issuer directory (which carries a
  current profile link per issuer), resolve the CR's Tadawul symbol via
  the entity's GLEIF name, and confirm the match by finding the CR in the
  profile page before trusting a single figure.

Identifiers:

* CR Number — 10 digits, ``IdentifierType.COMPANY_NUMBER`` (also covers
  the ``7``-prefixed GOSI/MoL 700 establishment number).
* VAT — 15 digits beginning with ``3``; a leading ``SA`` is stripped.

Per the project rules this adapter never returns mock data: name search
and CR lookup return only what GLEIF holds, financials come only from the
exchange's own table for the confirmed company, and VAT lookups (no free
structured source — ZATCA is reCAPTCHA-gated) raise
``AdapterNotImplementedError`` so the API surfaces a 501.
"""
from __future__ import annotations

import re

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.sa import gleif_sa, tadawul
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
)

_CR_RE = re.compile(r"^\d{10}$")
_VAT_RE = re.compile(r"^3\d{14}$")
_EST_700_RE = re.compile(r"^7\d{9}$")


def _normalize_cr(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _CR_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Saudi CR / 700 ID must be 10 digits, got: {value}"
        )
    return cleaned


def _normalize_vat(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("SA"):
        cleaned = cleaned[2:]
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Saudi VAT must be 15 digits starting with 3, got: {value}"
        )
    return cleaned


class SAAdapter(CountryAdapter):
    country_code = "SA"
    country_name = "Saudi Arabia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    _MAX_FINANCIAL_CANDIDATES = 3

    async def health_check(self) -> AdapterHealth:
        try:
            reachable = bool(await gleif_sa.search_sa("Saudi", limit=1))
        except Exception:
            reachable = False
        status = AdapterStatus.OK if reachable else AdapterStatus.ERROR
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via GLEIF (CR stored as registeredAs, RA000513); "
                "financials scraped from the Saudi Exchange company profile "
                "for TASI-listed issuers."
            )
            if reachable
            else "GLEIF unreachable from here.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        return await gleif_sa.search_sa(name, limit=limit)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            cr = _normalize_cr(value)
            return await gleif_sa.lookup_cr(cr)

        if id_type == IdentifierType.VAT:
            _normalize_vat(value)
            raise AdapterNotImplementedError(
                "Saudi VAT lookup has no free structured source; ZATCA's "
                "validator is reCAPTCHA-gated."
            )

        raise InvalidIdentifierError(
            f"Saudi Arabia supports COMPANY_NUMBER (CR or 700) and VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cr = _normalize_cr(company_id)
        names = await gleif_sa.name_variants_for_cr(cr)
        if not names:
            return []

        issuers = await tadawul.fetch_directory()
        candidates = tadawul.rank_candidates(issuers, names)[
            : self._MAX_FINANCIAL_CANDIDATES
        ]
        for issuer, exact in candidates:
            html = await tadawul.fetch_profile(issuer.profile_url)
            if not (exact or tadawul.page_confirms_cr(html, cr)):
                continue
            filings = tadawul.parse_financials(
                html,
                company_id=cr,
                symbol=issuer.symbol,
                source_url=issuer.profile_url,
                max_years=years,
            )
            if filings:
                return filings
        return []
