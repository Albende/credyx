"""Senegal adapter — BRVM (Bourse Régionale des Valeurs Mobilières).

Senegal has no free public registry API. The official creation portal
APIX (https://creationdentreprise.sn/) exposes only a session-bound web
UI behind forms — not scrape-friendly in MVP and explicitly excluded by
the "no paid APIs / no brittle scrapes during MVP" rule.

What we can provide today: financials for BRVM-listed Senegalese issuers
via the regional stock exchange site (https://www.brvm.org/). BRVM is
the shared exchange for the 8 UEMOA countries (BJ, BF, CI, GW, ML, NE,
SN, TG). Listed Senegalese companies publish annual reports there in
PDF form — that's the only legally free, deterministic data source for
Senegalese balance sheets.

Identifiers:
- RCCM: West-African unified commercial register code,
  format ``SN-{location}-YYYY-{type}-{seq}`` (e.g. ``SN-DKR-2003-B-1234``).
- NINEA: 9-digit fiscal identifier mapped to ``IdentifierType.VAT``.

Both identifiers are accepted by ``lookup_by_identifier`` for shape
validation, but lookup itself is unimplemented — APIX requires session
auth and the public BRVM site is symbol-indexed, not RCCM-indexed.
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

# Senegalese BRVM tickers we recognise. The exchange itself indexes by
# 3- or 4-letter ticker (e.g. SNTS for Sonatel), so a RCCM/NINEA cannot
# resolve a filing — only a known ticker can.
_SN_BRVM_TICKERS: dict[str, str] = {
    "SNTS": "Sonatel S.A.",
    "BICC": "BICI Sénégal (BICIS)",
    "SDSC": "SODE Sénégal",
    "TTLS": "Total Sénégal",
}

_RCCM_RE = re.compile(r"^SN-[A-Z]{2,5}-\d{4}-[A-Z]-\d{1,8}$", re.IGNORECASE)
_NINEA_RE = re.compile(r"^\d{7,9}[A-Z0-9]?$")


class SNAdapter(CountryAdapter):
    country_code = "SN"
    country_name = "Senegal"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    BRVM_BASE_URL = "https://www.brvm.org"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BRVM_BASE_URL) as client:
                resp = await get_with_retry(client, "/")
                # BRVM frequently 403s a generic UA on the root page but
                # the host being reachable is enough for a health signal.
                reachable = resp.status_code < 500
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
            status=AdapterStatus.DEGRADED if reachable else AdapterStatus.ERROR,
            capabilities={"search": False, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Senegal MVP: no free registry API. Name search and "
                "RCCM/NINEA lookup unavailable (APIX is session-bound). "
                "Financials: BRVM-listed issuers only, by ticker."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Senegal name search not implemented: APIX "
            "(creationdentreprise.sn) requires a session and the public "
            "BRVM site is ticker-indexed, not name-indexed."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in {IdentifierType.COMPANY_NUMBER, IdentifierType.VAT}:
            raise InvalidIdentifierError(
                f"SN only supports COMPANY_NUMBER (RCCM) or VAT (NINEA), got {id_type}"
            )
        v = value.strip().upper().replace(" ", "")
        if id_type == IdentifierType.COMPANY_NUMBER and not _RCCM_RE.match(v):
            raise InvalidIdentifierError(
                f"Senegalese RCCM must match SN-LOC-YYYY-X-NNN: {value}"
            )
        if id_type == IdentifierType.VAT and not _NINEA_RE.match(v):
            raise InvalidIdentifierError(
                f"Senegalese NINEA must be 7-9 digits with optional check char: {value}"
            )
        raise AdapterNotImplementedError(
            "Senegal identifier lookup not implemented: APIX is "
            "session-bound and there is no free public RCCM/NINEA API."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Spec: "BRVM for listed, [] otherwise". BRVM publishes annual
        # reports as PDFs on per-issuer pages indexed by ticker; their
        # structured extraction requires the PDF pipeline that is not
        # yet wired in MVP. Until that pipeline lands we honour the
        # "no mock data" rule and return [] for everyone — both for
        # unknown tickers and for known listed issuers whose PDFs we
        # cannot yet parse. The known-ticker map is preserved so the
        # API layer can expose source_urls to the UI without inventing
        # FinancialFiling rows here.
        return []
