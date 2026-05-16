"""DR Congo adapter — Guichet Unique / BCC (partial).

The Democratic Republic of the Congo has no free machine-readable corporate
registry. Identifiers (RCCM and NIF) are issued by the **Guichet Unique de
Création d'Entreprise** (https://guichetunique.cd/) — a one-stop registration
portal — but its public surface is a JS-rendered marketing site with no
documented REST API for company search or lookup. The **Banque Centrale du
Congo** (https://www.bcc.cd/) publishes macro-financial statistics and a
short list of supervised credit institutions but does not expose per-company
filings. DR Congo has no operating stock exchange.

For MVP we therefore:

- ``search_by_name`` / ``lookup_by_identifier`` → ``AdapterNotImplementedError``
- ``fetch_financials`` → ``[]`` (no free filings source)
- ``health_check`` → probes ``guichetunique.cd`` reachability

Identifiers:
- ``COMPANY_NUMBER`` → **RCCM** (Registre du Commerce et du Crédit Mobilier),
  OHADA-style, e.g. ``CD/KIN/RCCM/14-B-1234``.
- ``VAT`` → **NIF** (Numéro d'Identification Fiscale), 14 characters,
  e.g. ``A0801234X``.
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
    FinancialFiling,
    IdentifierType,
)


class CDAdapter(CountryAdapter):
    country_code = "CD"
    country_name = "DR Congo"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    GUICHET_URL = "https://guichetunique.cd/"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "No free official RCCM/NIF API. Guichet Unique exposes only a "
            "JS-rendered marketing site; BCC has no per-company filings. "
            "Search/lookup raise not_implemented; financials return []."
        )
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(
                    client, self.GUICHET_URL, max_attempts=2
                )
                reachable = resp.status_code < 500
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
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"Guichet Unique unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=(
                AdapterStatus.DEGRADED if reachable else AdapterStatus.ERROR
            ),
            capabilities={
                "search": False,
                "lookup": False,
                "financials": False,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "DR Congo has no free official RCCM search API. Guichet Unique "
            "does not expose a public name-search endpoint. Use GLEIF / "
            "OpenCorporates fallback for global name search."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(
            "DR Congo RCCM / NIF lookup requires an in-person request at the "
            "Guichet Unique de Création d'Entreprise or a paid extract. No "
            "free machine-readable endpoint exists."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        return []
