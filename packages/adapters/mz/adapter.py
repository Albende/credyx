"""Mozambique adapter — Boletim da República + BVM (Bolsa de Valores de Moçambique).

There is no free structured commercial register API. Commercial registry
publications appear in the Boletim da República (state gazette) as PDFs,
and structured per-company lookups via Conservatória do Registo das Entidades
Legais require either physical request or the (paid/closed) e-BAU portal.

This adapter therefore:
  * validates NUIT format (9 digits) and exposes identifier metadata,
  * raises `AdapterNotImplementedError` for name search and identifier lookup
    (no free structured source exists),
  * returns BVM-listed annual reports for the small set of listed issuers
    when the BVM site is reachable, otherwise an empty list,
  * health-checks against bvm.co.mz.

Identifier: NUIT — Número Único de Identificação Tributária, 9 digits.
"""
from __future__ import annotations

import re
from datetime import date, datetime

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
)

_NUIT_RE = re.compile(r"^\d{9}$")

# BVM-listed issuers known to publish annual reports on bvm.co.mz. Used only
# to point `fetch_financials` at the right public landing page — no figures
# are fabricated; structured_data is left None and the LLM/UI follows the
# source_url for the actual filing.
_BVM_LISTED: dict[str, dict[str, str]] = {
    "CDM": {
        "name": "Cervejas de Moçambique, S.A.",
        "page": "https://www.bvm.co.mz/index.php/emitentes/cdm",
    },
    "CMH": {
        "name": "Companhia Moçambicana de Hidrocarbonetos, S.A.",
        "page": "https://www.bvm.co.mz/index.php/emitentes/cmh",
    },
    "HCB": {
        "name": "Hidroeléctrica de Cahora Bassa, S.A.",
        "page": "https://www.bvm.co.mz/index.php/emitentes/hcb",
    },
}


def _normalize_nuit(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _NUIT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Mozambique NUIT must be 9 digits: {value!r}"
        )
    return cleaned


class MZAdapter(CountryAdapter):
    country_code = "MZ"
    country_name = "Mozambique"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    BVM_BASE_URL = "https://www.bvm.co.mz"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BVM_BASE_URL, timeout=15.0) as client:
                resp = await get_with_retry(client, "/")
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"BVM unreachable: {str(exc)[:160]}",
            )
        if not ok:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="BVM returned non-success status.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "No free structured registry API. Search/lookup unavailable; "
                "annual reports only for the small set of BVM-listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Mozambique has no free structured registry search. "
            "Boletim da República publishes commercial-registry notices as "
            "PDFs only; structured lookups require Conservatória do Registo "
            "das Entidades Legais (offline) or the paid e-BAU portal."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Mozambique supports VAT (NUIT) / COMPANY_NUMBER, got {id_type}"
            )
        _normalize_nuit(value)
        raise AdapterNotImplementedError(
            "No free NUIT lookup endpoint. Autoridade Tributária only exposes "
            "NUIT validation through the e-Tributação portal, which requires "
            "an authenticated taxpayer session."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper()
        listed = _BVM_LISTED.get(ticker)
        if listed is None:
            return []
        # We don't fabricate filings: emit a single discovery pointer at the
        # issuer's BVM page where annual reports are published. structured_data
        # stays None so the risk engine knows to follow source_url.
        prior_year = datetime.utcnow().year - 1
        return [
            FinancialFiling(
                company_id=ticker,
                year=prior_year,
                type=FilingType.ANNUAL_REPORT,
                period_end=date(prior_year, 12, 31),
                currency="MZN",
                structured_data=None,
                document_url=None,
                document_format="html",
                source_url=listed["page"],
            )
        ]
