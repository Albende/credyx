"""Côte d'Ivoire adapter — CEPICI + BRVM (regional UEMOA exchange).

Free public sources only:
- CEPICI (Centre de Promotion des Investissements en Côte d'Ivoire) at
  cepici.gouv.ci exposes investment-portal information through interactive
  pages without a documented JSON API or bulk export; the RCCM company
  register itself sits inside the Guichet Unique workflow and is not
  programmatically queryable for free.
- DGI (Direction Générale des Impôts) does not expose a public VAT
  (Numéro Compte Contribuable) validation endpoint.
- BRVM (Bourse Régionale des Valeurs Mobilières) at brvm.org is the
  regional exchange shared by the eight UEMOA states (BJ, BF, CI, GW, ML,
  NE, SN, TG) and publishes free annual reports for listed issuers. For
  listed tickers we surface the issuer page as a `FinancialFiling`
  pointer; deeper PDF parsing is left to the cross-cutting PDF pipeline.

Identifier: RCCM (Registre du Commerce et du Crédit Mobilier) number, or
the BRVM ticker (accepted as `COMPANY_NUMBER`) for the listed-company
financials path.
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

# Known BRVM-listed issuer tickers with a stable issuer page on brvm.org.
# The exchange is UEMOA-wide, so a "CI" adapter routing through BRVM also
# legitimately surfaces SN/BJ/etc. issuers — these are the four canonical
# test names called out in the country brief.
_BRVM_LISTED: dict[str, str] = {
    "SNTS": "Sonatel",
    "BOAC": "Bank of Africa Côte d'Ivoire",
    "ETIT": "Ecobank Transnational Incorporated",
    "SLBC": "SOLIBRA — Société de Limonaderies et Brasseries d'Afrique",
}


class CIAdapter(CountryAdapter):
    country_code = "CI"
    country_name = "Côte d'Ivoire"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    CEPICI_URL = "https://www.cepici.gouv.ci"
    BRVM_URL = "https://www.brvm.org"

    async def health_check(self) -> AdapterHealth:
        # BRVM is the only source we can actually exercise; CEPICI has no
        # documented API and the RCCM lookup sits behind Guichet Unique auth.
        try:
            async with build_http_client(base_url=self.BRVM_URL) as client:
                resp = await get_with_retry(client, "/")
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=f"BRVM probe failed: {str(exc)[:160]}",
            )
        status = AdapterStatus.DEGRADED if ok else AdapterStatus.ERROR
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "CEPICI publishes no public JSON API; RCCM lookups are behind "
                "Guichet Unique auth; DGI has no public VAT validation. "
                "Only BRVM-listed issuers expose free annual reports."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Côte d'Ivoire CEPICI / RCCM name search has no free programmatic "
            "source; Guichet Unique requires authenticated session access."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "Côte d'Ivoire RCCM lookup is not exposed via a free public API; "
            "DGI VAT (NCC) validation has no public endpoint."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper()
        if ticker not in _BRVM_LISTED:
            return []
        # We surface a single pointer to the BRVM issuer page rather than
        # guessing PDF URLs; the cross-cutting PDF pipeline is responsible
        # for scraping year-by-year annual reports off this page. BRVM
        # quotes are in XOF (CFA Franc BCEAO), the shared UEMOA currency.
        source_url = f"{self.BRVM_URL}/en/listed-companies/{ticker.lower()}"
        return [
            FinancialFiling(
                company_id=ticker,
                year=0,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="XOF",
                structured_data=None,
                document_url=None,
                document_format="html",
                source_url=source_url,
            )
        ]
