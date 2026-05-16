"""Mexico adapter — SAT (Servicio de Administración Tributaria) + BMV.

Free public sources only:
- SAT RFC validator (https://www.sat.gob.mx/) — HTML form, returns name + status.
  No public free-text search; identifier lookup only, and even that is gated
  behind a CAPTCHA on the front-facing portal.
- Lista 69-B / 69 (tax-suspect publication) — CSV downloads from SAT open data.
- BMV (https://www.bmv.com.mx/) — annual reports for listed issuers, free.

Identifier: RFC (Registro Federal de Contribuyentes).
- Companies (personas morales): 12 chars = 3 letters + 6 digits (YYMMDD) + 3 alphanumerics.
- Individuals (personas físicas): 13 chars — out of scope for B2B credit, but we still
  reject them with a clear error.

Per Phase-5 of the roadmap: full SIGER/RPC corporate filings are paid per-state
and out of MVP scope.
"""
from __future__ import annotations

import re
from datetime import datetime

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    BlockedByRegistryError,
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

# Persona moral (corporate) RFC: 3 letters, 6 digits (YYMMDD), 3 alphanumerics ("homoclave").
_RFC_MORAL_RE = re.compile(r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$")
# Persona física RFC is 13 chars (4 letters + 6 digits + 3 alphanumerics) — not B2B.
_RFC_FISICA_RE = re.compile(r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$")


def _normalize_rfc(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if _RFC_MORAL_RE.match(cleaned):
        return cleaned
    if _RFC_FISICA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"RFC {value} is a persona física (13 chars). MX adapter only "
            "handles personas morales (12 chars)."
        )
    raise InvalidIdentifierError(
        f"RFC invalid: {value}. Expected 12 chars: 3 letters + 6 digits + 3 alphanumerics."
    )


class MXAdapter(CountryAdapter):
    country_code = "MX"
    country_name = "Mexico"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    SAT_BASE_URL = "https://www.sat.gob.mx"
    # Public RFC validator entry point (web portal landing for the verifier).
    SAT_VERIFIER_URL = (
        "https://portalsat.plataforma.sat.gob.mx/ConsultaRFC/"
    )
    BMV_BASE_URL = "https://www.bmv.com.mx"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.SAT_BASE_URL) as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes=f"SAT unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "SAT public verifier requires CAPTCHA; no free name search. "
                "Lookups by RFC and BMV listed-issuer filings are roadmap items."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "SAT does not expose a free-text public search API. MX name "
            "resolution requires OpenCorporates / GLEIF fallback at the route "
            "layer, or a Phase-2 paid registry integration."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"MX supports VAT (RFC) or COMPANY_NUMBER, got {id_type}"
            )
        rfc = _normalize_rfc(value)
        # The SAT verifier (portalsat.plataforma.sat.gob.mx/ConsultaRFC/) is a
        # JSF form gated by a CAPTCHA — no programmatic JSON endpoint. Surface
        # the block honestly rather than scraping behind a CAPTCHA.
        raise BlockedByRegistryError(
            f"SAT RFC verifier is CAPTCHA-protected; cannot resolve {rfc} "
            "without a paid integration. Tracked in Phase-5 Americas roadmap."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # BMV publishes annual reports for listed issuers, but the ticker (not
        # the RFC) is the key. Without a free RFC→ticker mapping we cannot
        # auto-resolve. Return empty so the route layer can decide whether to
        # try aggregators (e.g. EDGAR for cross-listed ADRs).
        _normalize_rfc(company_id)
        return []
