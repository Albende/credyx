"""Seychelles adapter — MERJ Exchange (free, listed-only) + FSA shell.

The Seychelles is a small offshore jurisdiction with a notoriously opaque
corporate registry. The Financial Services Authority (FSA Seychelles) is
the official regulator of International Business Companies (IBCs), but
the IBC database is *not* publicly searchable: full registry extracts are
paid per document, and beneficial-owner data is held privately under
Seychelles AML legislation. That puts FSA squarely outside the MVP rule
against paid commercial sources (see ``CLAUDE.md`` non-negotiables).

What *is* free and authoritative:

- **MERJ Exchange** (https://merj.exchange/) — Seychelles' licensed
  securities exchange. Each listed issuer has a public profile page with
  annual reports as PDFs. The universe is tiny (a handful of issuers) but
  the data is real and free, which is the only thing we accept here.

What this adapter therefore does:

- ``search_by_name`` and ``lookup_by_identifier`` raise
  :class:`AdapterNotImplementedError` — the API surface turns that into a
  501 with ``status="not_implemented"``. We never fabricate registry rows.
- ``fetch_financials`` returns ``[]`` for unknown company numbers and a
  MERJ issuer-page link for the handful we have verified.
- ``health_check`` probes MERJ for reachability.

**Offshore-jurisdiction caveat — sanctions / PEP screening is required.**
Seychelles IBCs are repeatedly named in offshore-leak datasets (Panama
Papers, Paradise Papers, Pandora Papers) and feature in OFAC / EU
sanctions designations. Any credit decision involving an SC counterparty
SHOULD route through ``packages._global.opensanctions`` before the LLM
sees the file. See ``docs/countries/sc.md`` for the rationale.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterNotImplementedError, InvalidIdentifierError
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

_SC_COMPANY_NUMBER_RE = re.compile(r"^[A-Z0-9]{4,15}$")

# MERJ-listed issuers we have verified expose free annual reports on their
# public issuer page. Kept tiny on purpose — adding a new slug requires
# manually confirming the URL resolves on merj.exchange.
_MERJ_ISSUER_SLUGS: dict[str, str] = {}


_NOT_IMPLEMENTED_NOTE = (
    "Seychelles FSA registry is paywalled and not publicly searchable; "
    "no free name search or per-identifier lookup is available. "
    "OFFSHORE NOTORIETY: SC IBCs frequently appear in sanctions and "
    "offshore-leak datasets — screen via OpenSanctions before any credit "
    "decision."
)


def _normalize_company_number(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if not _SC_COMPANY_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Seychelles company number invalid: {value}"
        )
    return cleaned


class SCAdapter(CountryAdapter):
    country_code = "SC"
    country_name = "Seychelles"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    MERJ_BASE = "https://merj.exchange"
    FSA_BASE = "https://fsaseychelles.sc"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(client, self.MERJ_BASE + "/")
        except httpx.HTTPError as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"MERJ probe failed: {str(exc)[:160]}",
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"MERJ returned {resp.status_code}.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "FSA Seychelles registry is paywalled; only MERJ-listed "
                "issuer financials are exposed. Offshore-jurisdiction risk "
                "— OpenSanctions screening required before credit decision."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(_NOT_IMPLEMENTED_NOTE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(_NOT_IMPLEMENTED_NOTE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cn = _normalize_company_number(company_id)
        slug = _MERJ_ISSUER_SLUGS.get(cn)
        if slug is None:
            return []
        issuer_url = f"{self.MERJ_BASE}/issuers/{slug}/"
        prior_year = datetime.utcnow().year - 1
        return [
            FinancialFiling(
                company_id=cn,
                year=prior_year,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency=None,
                structured_data=None,
                document_url=issuer_url,
                document_format="html",
                source_url=issuer_url,
            )
        ]
