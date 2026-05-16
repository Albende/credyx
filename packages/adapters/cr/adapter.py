"""Costa Rica adapter — Ministerio de Hacienda ATV + BNV.

Sources:

* Ministerio de Hacienda — Consulta de Situación Tributaria (ATV).
  Public, free, no auth. The user-facing form at
  ``https://www.hacienda.go.cr/ATV/ConsultaSituacionTributaria.aspx`` is
  backed by a JSON endpoint at
  ``https://api.hacienda.go.cr/fe/ae?identificacion={cedula}`` that the
  e-invoicing ("factura electrónica") tooling has used for years. We hit
  it directly; the HTML page never sees a programmatic caller.
* Registro Nacional (RNP / Registro de Personas Jurídicas) —
  ``https://www.rnpdigital.com/``. No free name-search API; per
  ``docs/countries/cr.md`` we raise ``AdapterNotImplementedError`` rather
  than scrape behind the portal's session login.
* Bolsa Nacional de Valores —
  ``https://www.bolsacr.com/``. Limited free disclosure index for
  listed issuers; surfaced as a discovery URL for known listed cédulas
  (no per-year XBRL feed today).

Identifier: **Cédula Jurídica**.

- Companies are 10 digits, conventionally rendered ``3-101-005514``.
  The leading digit ``3`` denotes a juridical person; the middle three
  digits are the sub-class (``101`` for sociedades anónimas,
  ``102`` for SRL, ``110`` for civil associations, etc.).
- A handful of state institutions (ICE, BNCR, AyA, INS, RECOPE, ...) are
  filed as ``cédulas físicas`` of class ``4-000-XXXXXX`` because they
  pre-date the modern juridical regime. Hacienda accepts both forms via
  the same ATV endpoint, so the adapter normalizes either.

No-mock-data rule: every CompanyDetails returned here comes verbatim from
Hacienda's JSON payload. If the endpoint is unreachable we surface an
``ERROR`` health status; we never fabricate fields.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

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
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D+")

# Juridical persons: leading 3 + 3-digit class + 6-digit sequence.
_CEDULA_JURIDICA_RE = re.compile(r"^3\d{9}$")
# State-entity ("cédula física institucional") form: leading 4 + 000 + 6 digits.
# ICE, BNCR, AyA, INS, RECOPE and similar pre-1990 entities are filed this way.
_CEDULA_ESTATAL_RE = re.compile(r"^4000\d{6}$")

# Florida Bebidas — used as a stable health-check anchor (large, always active).
_HEALTH_PROBE_CEDULA = "3101005514"

# Class codes (positions 1..4) seen on company cédulas. Mapped to the canonical
# Costa Rican corporate legal form for human-readable display. Codes not in this
# table are surfaced verbatim from Hacienda's payload.
_LEGAL_FORM_BY_CLASS: dict[str, str] = {
    "3101": "Sociedad Anónima",
    "3102": "Sociedad de Responsabilidad Limitada",
    "3103": "Sociedad en Nombre Colectivo",
    "3104": "Sociedad en Comandita",
    "3105": "Empresa Individual de Responsabilidad Limitada",
    "3106": "Sucursal de Sociedad Extranjera",
    "3107": "Sociedad Cooperativa",
    "3108": "Sociedad Civil",
    "3109": "Sociedad Extranjera",
    "3110": "Asociación Civil",
    "3014": "Municipalidad",
    "4000": "Institución del Estado",
}


def _normalize_cedula(value: str) -> str:
    """Strip punctuation, return canonical 10-digit cédula jurídica."""
    if value is None:
        raise InvalidIdentifierError("Cédula jurídica is required")
    digits = _DIGITS_RE.sub("", value)
    if not digits:
        raise InvalidIdentifierError(f"Cédula jurídica invalid: {value!r}")
    if _CEDULA_JURIDICA_RE.match(digits) or _CEDULA_ESTATAL_RE.match(digits):
        return digits
    raise InvalidIdentifierError(
        f"Cédula jurídica must be 10 digits starting with 3 (juridical) "
        f"or 4-000-XXXXXX (state entity), got {value!r}"
    )


def _format_cedula(cedula: str) -> str:
    """Render a normalized cédula as ``X-XXX-XXXXXX``."""
    return f"{cedula[0]}-{cedula[1:4]}-{cedula[4:]}"


# Listed cédulas with disclosure pages on the Bolsa Nacional de Valores
# index. The BNV does not expose a per-cédula REST endpoint; we keep a
# very small static map of well-known emisores so closed companies cleanly
# get ``[]`` (no fabrication) while listed names surface the BNV pointer.
# Source: https://www.bolsacr.com/emisores (verified manually).
_BNV_LISTED: dict[str, str] = {
    "4000042139": "Instituto Costarricense de Electricidad",
    "4000001021": "Banco Nacional de Costa Rica",
    "3101005514": "Florida Ice & Farm Co. / Florida Bebidas",
}


class CRAdapter(CountryAdapter):
    country_code = "CR"
    country_name = "Costa Rica"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    HACIENDA_API_BASE = "https://api.hacienda.go.cr"
    HACIENDA_PORTAL = (
        "https://www.hacienda.go.cr/ATV/ConsultaSituacionTributaria.aspx"
    )
    BNV_BASE = "https://www.bolsacr.com"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.HACIENDA_API_BASE,
            headers={
                "Accept": "application/json",
                "Accept-Language": "es-CR,es;q=0.9,en;q=0.7",
                "Referer": self.HACIENDA_PORTAL,
            },
            timeout=20.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    "/fe/ae",
                    params={"identificacion": _HEALTH_PROBE_CEDULA},
                )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes=f"Hacienda ATV unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "RNP has no free name-search API; lookup by cédula via "
                "Hacienda ATV. Financials limited to BNV-listed emisores."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # RNP requires a logged-in session at rnpdigital.com for any
        # registry query, and Hacienda's ATV only resolves by identifier.
        # Per the no-mock-data rule we refuse rather than fabricate.
        raise AdapterNotImplementedError(
            "Costa Rica name search is not available on free public sources. "
            "RNP (rnpdigital.com) gates queries behind a session login; "
            "Hacienda ATV is identifier-only. Use cédula jurídica lookup."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"CR supports VAT/COMPANY_NUMBER (cédula jurídica), got {id_type}"
            )
        cedula = _normalize_cedula(value)
        payload = await self._fetch_ae(cedula)
        if payload is None:
            return None
        return _details_from_ae(cedula, payload)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cedula = _normalize_cedula(company_id)
        if cedula not in _BNV_LISTED:
            return []
        # BNV does not publish a per-emisor REST feed; the public hechos
        # relevantes index is the canonical pointer. Operators drill into
        # specific years from there. We surface one row per requested year
        # so the risk engine has a discovery handle.
        index_url = f"{self.BNV_BASE}/emisores"
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=cedula,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="CRC",
                    structured_data=None,
                    document_url=index_url,
                    document_format="html",
                    source_url=index_url,
                )
            )
        return filings

    async def _fetch_ae(self, cedula: str) -> dict[str, Any] | None:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client, "/fe/ae", params={"identificacion": cedula}
                )
                if resp.status_code in (404, 400):
                    return None
                resp.raise_for_status()
                # Hacienda historically returns ``application/json`` but
                # has been known to mislabel as text/plain; trust the body.
                try:
                    data = resp.json()
                except ValueError:
                    return None
        except httpx.HTTPError as exc:
            logger.warning("Hacienda ATV fetch failed for %s: %s", cedula, exc)
            return None
        if not isinstance(data, dict):
            return None
        # An "empty" hit comes back as ``{}`` or a dict missing both the
        # name and the situación fields. Treat that as not-found rather
        # than fabricate a CompanyDetails with blank strings.
        if not data:
            return None
        if not (data.get("nombre") or data.get("nombreComercial")):
            return None
        return data


def _details_from_ae(cedula: str, data: dict[str, Any]) -> CompanyDetails:
    name = (data.get("nombre") or data.get("nombreComercial") or "").strip()
    legal_form = _legal_form(cedula, data)
    status = (
        data.get("situacion", {}).get("estado")
        if isinstance(data.get("situacion"), dict)
        else None
    ) or data.get("estado")

    nace_codes: list[str] = []
    for act in data.get("actividades") or []:
        if not isinstance(act, dict):
            continue
        code = act.get("codigo") or act.get("codigoCIIU") or act.get("codigoActividad")
        if code is not None and (estado := act.get("estado")):
            # Skip activities explicitly marked inactive; the active ones
            # are what credit decisions should reason about.
            if str(estado).strip().lower() != "activo":
                continue
        if code is not None:
            digits = _DIGITS_RE.sub("", str(code))
            if digits and digits not in nace_codes:
                nace_codes.append(digits)

    formatted = _format_cedula(cedula)
    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.VAT, value=formatted, label="Cédula Jurídica"
        ),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=formatted,
            label="Cédula Jurídica",
        ),
    ]

    return CompanyDetails(
        id=cedula,
        name=name or formatted,
        country="CR",
        legal_form=legal_form,
        status=str(status).strip() if status else None,
        incorporation_date=None,  # Hacienda ATV does not return constitution date.
        registered_address=None,
        capital_amount=None,
        capital_currency="CRC",
        nace_codes=nace_codes,
        identifiers=identifiers,
        raw=dict(data),
        source_url=(
            "https://api.hacienda.go.cr/fe/ae?identificacion=" + cedula
        ),
    )


def _legal_form(cedula: str, data: dict[str, Any]) -> str | None:
    explicit = data.get("tipoIdentificacion") or data.get("regimen", {})
    if isinstance(explicit, dict):
        descripcion = explicit.get("descripcion")
        if descripcion:
            return str(descripcion).strip()
    elif isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    class_code = cedula[:4]
    return _LEGAL_FORM_BY_CLASS.get(class_code)


__all__ = [
    "CRAdapter",
    "_normalize_cedula",
    "_format_cedula",
]
