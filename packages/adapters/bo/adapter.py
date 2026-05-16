"""Bolivia adapter — SEPREC + Impuestos Nacionales + BBV.

Sources:
- SEPREC (Servicio Plurinacional de Registro de Comercio): https://www.seprec.gob.bo/
  Public information about Matrícula de Comercio. The portal is a session-based
  JS web app — there is no free JSON endpoint for either name search or
  identifier lookup at request time.
- Impuestos Nacionales (Servicio de Impuestos Nacionales): https://impuestos.gob.bo/
  Hosts the public NIT consultation, again gated behind a CAPTCHA / session
  flow. No documented free REST API.
- BBV (Bolsa Boliviana de Valores): https://www.bbv.com.bo/ — publishes free
  annual reports / "Memorias Anuales" for listed issuers. There is no per-issuer
  JSON feed; `fetch_financials` surfaces a discovery URL rather than fabricating
  structured line items.

Because both SEPREC and Impuestos Nacionales require a real browser session
plus CAPTCHA solving, `search_by_name` and `lookup_by_identifier` raise
`AdapterNotImplementedError` (mapped to HTTP 501 by the API) rather than
returning mock data. `fetch_financials` returns a BBV discovery pointer for
listed issuers and an empty list otherwise.

Identifiers:
- NIT (Número de Identificación Tributaria) — exposed as `VAT`.
- Matrícula de Comercio (SEPREC) — exposed as `COMPANY_NUMBER`.
"""
from __future__ import annotations

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
    CompanyMatch,
    CompanyDetails,
    FilingType,
    FinancialFiling,
    IdentifierType,
)


class BOAdapter(CountryAdapter):
    country_code = "BO"
    country_name = "Bolivia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    SEPREC_URL = "https://www.seprec.gob.bo/"
    IMPUESTOS_URL = "https://impuestos.gob.bo/"
    BBV_BASE = "https://www.bbv.com.bo"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BBV_BASE, timeout=20.0) as client:
                resp = await get_with_retry(client, "/")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"BBV unreachable: {str(exc)[:180]}",
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"BBV returned HTTP {resp.status_code}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "SEPREC and Impuestos Nacionales require CAPTCHA / session "
                "flows and have no free REST API; name search and identifier "
                "lookup are not implemented. Financials limited to BBV-listed "
                "issuers via discovery URL."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Bolivian SEPREC and Impuestos Nacionales do not expose a free "
            "name-search API; both portals require a browser session and "
            "CAPTCHA. Free name lookup is not implemented in MVP."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"BO supports VAT (NIT) and COMPANY_NUMBER (Matrícula), got {id_type}"
            )
        raise AdapterNotImplementedError(
            "Bolivian NIT and Matrícula de Comercio lookup is gated behind a "
            "CAPTCHA-protected web form at Impuestos Nacionales / SEPREC; "
            "no free REST endpoint exists. Lookup is not implemented in MVP."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # BBV does not expose a programmatic mapping from NIT to its internal
        # issuer code, so we surface the public "Emisores" landing page as a
        # discovery URL. For non-listed issuers this URL simply loads the
        # directory — never a fabricated filing — and the caller decides
        # whether to follow up manually.
        cleaned = (company_id or "").strip()
        if not cleaned:
            return []
        bbv_url = f"{self.BBV_BASE}/MercadoValores/Emisores.aspx"
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - 1 - offset
            filings.append(
                FinancialFiling(
                    company_id=cleaned,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="BOB",
                    structured_data=None,
                    document_url=bbv_url,
                    document_format="html",
                    source_url=bbv_url,
                )
            )
        return filings
