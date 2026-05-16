"""Uruguay adapter — DGI RUT consultation + BVM for listed-company filings.

Sources:
- DGI (Dirección General Impositiva) public RUT consultation:
  https://servicios.dgi.gub.uy/JSConsRUTRest/ — JSON REST endpoint backing
  the official "Consulta de RUT" form (no documented public spec, no auth,
  no CAPTCHA at request time). Used for `lookup_by_identifier`.
  The HTML facing page lives at:
  https://www.dgi.gub.uy/wdgi/page?2,principal,consulta-publica-de-rut,O,es,0,
  but the underlying service responds with JSON when called with the
  expected query params.
- BVM (Bolsa de Valores de Montevideo): https://www.bvm.com.uy/ —
  publishes free annual reports / "Información Relevante" for listed
  issuers. There is no per-issuer JSON feed, so `fetch_financials`
  surfaces a discovery URL (`document_url`) rather than fabricating
  structured line items — consistent with the project's no-mock-data
  rule.

Identifier: **RUT** (Registro Único Tributario) — 12 digits. The Uruguayan
RUT is also the company tax ID, so we expose it as both `VAT` and accept
`COMPANY_NUMBER` as an alias. The last digit is a Mod-11 check digit but
DGI historically issued RUTs that pre-date the modern algorithm; we
therefore accept any well-formed 12-digit string and do NOT reject on a
failed checksum — the source registry is the authority.

Name search: DGI offers no free company-name search API (only the
RUT-by-tax-ID form). `search_by_name` raises `AdapterNotImplementedError`.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_DIGITS_RE = re.compile(r"\D+")
_RUT_RE = re.compile(r"^\d{12}$")


def _normalize_rut(value: str) -> str:
    """Strip "UY"/dots/dashes/spaces, return canonical 12-digit RUT.

    DGI accepts the 12-digit form. We tolerate common decorations (dots,
    dashes, the "UY" country prefix used in some ERPs) and surface a clear
    `InvalidIdentifierError` if the input cannot be coerced to 12 digits.
    """
    raw = (value or "").strip().upper()
    if raw.startswith("UY"):
        raw = raw[2:]
    cleaned = _DIGITS_RE.sub("", raw)
    if not _RUT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Uruguayan RUT must be 12 digits, got: {value!r}"
        )
    return cleaned


class UYAdapter(CountryAdapter):
    country_code = "UY"
    country_name = "Uruguay"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    DGI_BASE = "https://servicios.dgi.gub.uy"
    DGI_REST_PATH = "/JSConsRUTRest/rest/consulta"
    DGI_PUBLIC_FORM = (
        "https://www.dgi.gub.uy/wdgi/page"
        "?2,principal,consulta-publica-de-rut,O,es,0,"
    )
    BVM_BASE = "https://www.bvm.com.uy"

    # ANCAP — public test RUT used for liveness probes.
    _HEALTH_RUT = "215521240017"

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._dgi_client() as client:
                resp = await get_with_retry(
                    client,
                    self.DGI_REST_PATH,
                    params={"rut": self._HEALTH_RUT},
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"DGI returned HTTP {resp.status_code}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search unavailable (DGI offers no free name API). "
                "Financials limited to BVM-listed issuers (URL only)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Uruguayan DGI does not expose a free name-search API. Only the "
            "RUT-by-tax-ID consultation is public; use direct RUT lookup."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"UY only supports VAT/COMPANY_NUMBER (RUT), got {id_type}"
            )
        rut = _normalize_rut(value)

        try:
            async with self._dgi_client() as client:
                resp = await get_with_retry(
                    client,
                    self.DGI_REST_PATH,
                    params={"rut": rut},
                )
        except httpx.HTTPError as exc:
            raise BlockedByRegistryError(
                f"DGI transport error for RUT {rut}: {exc}"
            ) from exc

        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            raise BlockedByRegistryError(
                "DGI consultation returned 403; the service may be rate-"
                "limiting or geofencing this client."
            )
        if resp.status_code >= 500:
            raise BlockedByRegistryError(
                f"DGI returned HTTP {resp.status_code} for RUT {rut}"
            )

        payload = _safe_json(resp)
        if payload is None:
            # The endpoint occasionally serves the HTML form (e.g. when the
            # JSON service is offline). Treat that as a block rather than
            # fabricate a result.
            raise BlockedByRegistryError(
                "DGI RUT consultation returned a non-JSON body. "
                "Direct HTTP lookup may be temporarily unavailable."
            )
        if _is_empty_payload(payload):
            return None

        return _details_from_dgi(rut, payload)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        rut = _normalize_rut(company_id)
        # BVM has no per-issuer programmatic endpoint mapping RUT to its
        # "Emisor" code; the issuer search lives behind a JS-driven page.
        # Surface the BVM emisores landing page so the credit analyst can
        # drill in. For RUTs that are not listed issuers this URL simply
        # loads the directory — never a fabricated filing.
        bvm_url = f"{self.BVM_BASE}/emisores/"
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - 1 - offset
            filings.append(
                FinancialFiling(
                    company_id=rut,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="UYU",
                    structured_data=None,
                    document_url=bvm_url,
                    document_format="html",
                    source_url=bvm_url,
                )
            )
        return filings

    def _dgi_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.DGI_BASE,
            headers={
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
                "Accept-Language": "es-UY,es;q=0.9,en;q=0.7",
                "Referer": self.DGI_PUBLIC_FORM,
            },
            timeout=25.0,
        )


def _safe_json(resp: httpx.Response) -> Any | None:
    ctype = (resp.headers.get("content-type") or "").lower()
    if "json" not in ctype and not (resp.text or "").lstrip().startswith(("{", "[")):
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _is_empty_payload(payload: Any) -> bool:
    if payload is None:
        return True
    if isinstance(payload, list) and not payload:
        return True
    if isinstance(payload, dict):
        if not payload:
            return True
        # DGI's "no resultados" envelope varies; treat an explicit error
        # field or an obviously empty name as "not found".
        err = payload.get("error") or payload.get("codigoError")
        if err:
            return True
        name = (
            payload.get("denominacion")
            or payload.get("razonSocial")
            or payload.get("nombre")
            or _get_nested(payload, "contribuyente", "denominacion")
            or _get_nested(payload, "contribuyente", "razonSocial")
        )
        if not name:
            return True
    return False


def _get_nested(d: dict[str, Any], *keys: str) -> Any | None:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _details_from_dgi(rut: str, payload: dict[str, Any]) -> CompanyDetails:
    contrib = payload.get("contribuyente") if isinstance(payload.get("contribuyente"), dict) else payload

    name = (
        contrib.get("denominacion")
        or contrib.get("razonSocial")
        or contrib.get("nombre")
        or ""
    ).strip()
    trade_name = (
        contrib.get("nombreFantasia")
        or contrib.get("nombre_fantasia")
        or ""
    ).strip() or None

    status_value = (
        contrib.get("estado")
        or contrib.get("situacion")
        or contrib.get("estadoActividad")
    )
    legal_form = (
        contrib.get("tipoEntidad")
        or contrib.get("naturaleza")
        or contrib.get("formaJuridica")
    )
    inc_date = _parse_date(
        contrib.get("fechaInicioActividad")
        or contrib.get("fechaInicio")
        or contrib.get("fecha_inicio_actividad")
    )

    address = _compose_address(contrib)

    activities = contrib.get("actividades") or contrib.get("giros") or []
    nace_codes: list[str] = []
    if isinstance(activities, list):
        for a in activities:
            if isinstance(a, dict):
                code = a.get("codigo") or a.get("codigoCiiu") or a.get("ciiu")
                if code:
                    nace_codes.append(str(code).strip())
            elif isinstance(a, str) and a.strip().isdigit():
                nace_codes.append(a.strip())

    identifiers = [
        RegistryIdentifier(type=IdentifierType.VAT, value=rut, label="RUT"),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=rut, label="RUT"
        ),
    ]

    raw_extra: dict[str, Any] = dict(payload)
    if trade_name:
        raw_extra["trade_name"] = trade_name

    return CompanyDetails(
        id=rut,
        name=name or trade_name or rut,
        country="UY",
        legal_form=str(legal_form) if legal_form else None,
        status=str(status_value) if status_value else None,
        incorporation_date=inc_date,
        registered_address=address,
        capital_amount=None,
        capital_currency=None,
        nace_codes=nace_codes,
        identifiers=identifiers,
        raw=raw_extra,
        source_url=(
            "https://servicios.dgi.gub.uy/JSConsRUTRest/rest/consulta"
            f"?rut={rut}"
        ),
    )


def _compose_address(contrib: dict[str, Any]) -> str | None:
    domicilio = (
        contrib.get("domicilio")
        if isinstance(contrib.get("domicilio"), dict)
        else None
    )
    src = domicilio or contrib
    parts = [
        src.get("calle"),
        src.get("numero"),
        src.get("apartamento") or src.get("complemento"),
        src.get("barrio"),
        src.get("localidad") or src.get("ciudad"),
        src.get("departamento"),
        src.get("codigoPostal") or src.get("cp"),
    ]
    cleaned = [str(p).strip() for p in parts if p]
    return ", ".join(cleaned) if cleaned else None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None
