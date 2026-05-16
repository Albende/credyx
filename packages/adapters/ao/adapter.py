"""Angola adapter — partial coverage.

Angola has no free, programmatic company registry. The Guichê Único da
Empresa (GUE, https://gue.gov.ao/) and AGT NIF validator both gate access
behind interactive web forms / e-ID; neither exposes a documented JSON
search or lookup endpoint suitable for unauthenticated server-side use.

What IS feasible without paid data:

- BODIVA (Bolsa de Dívida e Valores de Angola, https://www.bodiva.ao/)
  publishes issuer disclosures for listed entities (bonds + the limited
  equity book). For an issuer we already know about, we can surface a
  pointer to its disclosure page. We do NOT scrape the BODIVA HTML for
  numbers — that path is brittle and would risk fabricating ratios; the
  PDF-extraction pipeline (see CLAUDE.md cross-cutting infra item 1) is
  the proper home for that work.

So this adapter:
  * raises `AdapterNotImplementedError` for search and lookup,
  * returns `[]` from `fetch_financials` (no fabricated data — see rule 1),
  * probes bodiva.ao in `health_check` and reports DEGRADED with a clear
    note pointing at the missing free-registry story.

Identifier: NIF — 10 chars, mix of letters and digits (e.g. 5417000000
for legal persons, leading "0" for sole proprietors). We expose it as
`IdentifierType.NIF` and accept `IdentifierType.VAT` and
`IdentifierType.COMPANY_NUMBER` as aliases since Angolan documents use
all three names interchangeably.
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

_NIF_RE = re.compile(r"^[A-Z0-9]{10}$")

_NOT_IMPLEMENTED_NOTE = (
    "Angola has no free programmatic registry. GUE (gue.gov.ao) and AGT "
    "NIF validator are interactive only; BODIVA covers listed issuers "
    "via HTML disclosure pages, no JSON. Paid integrations are out of "
    "scope for the MVP."
)


def _normalize_nif(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if not _NIF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Angolan NIF must be 10 alphanumeric characters: {value}"
        )
    return cleaned


class AOAdapter(CountryAdapter):
    country_code = "AO"
    country_name = "Angola"
    identifier_types = [
        IdentifierType.NIF,
        IdentifierType.VAT,
        IdentifierType.COMPANY_NUMBER,
    ]
    primary_identifier = IdentifierType.NIF
    requires_api_key = False
    rate_limit_per_minute = 30

    BODIVA_URL = "https://www.bodiva.ao/"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Partial: GUE/AGT have no public API; BODIVA covers listed "
            "issuers only via HTML. Search/lookup unavailable."
        )
        try:
            async with build_http_client(timeout=10.0) as client:
                resp = await get_with_retry(client, self.BODIVA_URL)
                bodiva_reachable = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=f"bodiva.ao unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED if bodiva_reachable else AdapterStatus.ERROR,
            capabilities={
                "search": False,
                "lookup": False,
                "financials": bodiva_reachable,
            },
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes if bodiva_reachable else "bodiva.ao returned 5xx",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(_NOT_IMPLEMENTED_NOTE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in self.identifier_types:
            raise InvalidIdentifierError(
                f"AO accepts NIF / VAT / COMPANY_NUMBER, got {id_type}"
            )
        # Validate format so the caller gets a fast 4xx instead of a 501
        # for obviously malformed input — then surface the real coverage gap.
        _normalize_nif(value)
        raise AdapterNotImplementedError(_NOT_IMPLEMENTED_NOTE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # BODIVA disclosure HTML is not structured; until the PDF/HTML
        # extraction pipeline is wired (CLAUDE.md infra item 1), we return
        # nothing rather than fabricate. A future implementation can fetch
        # the issuer's disclosure index from bodiva.ao and emit one
        # `FinancialFiling` per published annual report with
        # `document_url` pointing at the source PDF.
        return []
