"""Cameroon adapter — BVMAC (Bourse des Valeurs Mobilières d'Afrique Centrale).

Cameroon does not publish an official, free, machine-readable corporate registry.
The Centre de Formalités de Création d'Entreprises (CFCE) issues RCCM / NIU but
exposes no public REST API. The Douala-based regional CEMAC stock exchange
(BVMAC, https://www.bvm-ac.com/) lists a small number of Cameroonian issuers and
publishes their annual reports as downloadable PDFs.

For MVP we therefore:

- search_by_name / lookup_by_identifier → AdapterNotImplementedError
  (no official free machine-readable registry is available; the operator must
  fall back to GLEIF / OpenCorporates for global coverage)
- fetch_financials → curated map of BVMAC-listed issuers → public landing URLs
  for their annual reports. Returns [] for any non-listed company.

Identifiers:
- RCCM  → COMPANY_NUMBER (e.g. "RC/DLA/1968/B/1234")
- NIU   → VAT           (e.g. "M021400012345D")
"""
from __future__ import annotations

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterNotImplementedError
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


# BVMAC-listed Cameroonian issuers. The site does not expose a stable per-ticker
# JSON endpoint, so we link out to the public issuer landing page. Keys are
# lowercased common names; values are (display_name, landing_url).
_BVMAC_ISSUERS: dict[str, tuple[str, str]] = {
    "safacam": (
        "SAFACAM (Société Africaine Forestière et Agricole du Cameroun)",
        "https://www.bvm-ac.com/",
    ),
    "socapalm": (
        "SOCAPALM (Société Camerounaise de Palmeraies)",
        "https://www.bvm-ac.com/",
    ),
    "semc": (
        "SEMC (Société des Eaux Minérales du Cameroun)",
        "https://www.bvm-ac.com/",
    ),
}


class CMAdapter(CountryAdapter):
    country_code = "CM"
    country_name = "Cameroon"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    BVMAC_URL = "https://www.bvm-ac.com/"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "No free official RCCM/NIU API. Only BVMAC-listed issuers are "
            "supported for financials; search/lookup raise not_implemented."
        )
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(client, self.BVMAC_URL)
                reachable = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=f"BVMAC unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED if reachable else AdapterStatus.ERROR,
            capabilities={"search": False, "lookup": False, "financials": reachable},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Cameroon has no free official RCCM search API. "
            "Use GLEIF / OpenCorporates fallback for name search."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "Cameroon RCCM / NIU lookup requires a paid or in-person request "
            "at the CFCE. No free machine-readable endpoint exists."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        key = (company_id or "").strip().lower()
        issuer = _BVMAC_ISSUERS.get(key)
        if issuer is None:
            return []
        _, landing = issuer
        # BVMAC publishes the latest annual report on the issuer landing page;
        # we surface a single pointer rather than fabricate period_end dates.
        return [
            FinancialFiling(
                company_id=company_id,
                year=0,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="XAF",
                structured_data=None,
                document_url=landing,
                document_format="html",
                source_url=landing,
            )
        ]
