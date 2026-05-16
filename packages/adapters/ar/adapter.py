"""Argentina adapter — AFIP padron (CUIT) + CNV for listed-company financials.

Sources:
- AFIP "sr-padron" v2 REST: https://soa.afip.gob.ar/sr-padron/v2/persona/{cuit}
  Free, no auth. Returns tax registry record: razón social, address, activity
  codes, tax status. Covers every CUIT (companies + sole traders).
- CNV (Comisión Nacional de Valores) for listed companies' annual reports.
  Free, but only public-equity issuers — most CUITs return nothing here.

Identifier: CUIT — 11 digits, formatted XX-XXXXXXXX-X. The first two digits
classify the entity (30/33/34 = company, 20/23/24/27 = individual, etc.).
Mod-11 checksum on the 10 leading digits validates the trailing check digit.

Name search is not exposed by AFIP padron, so `search_by_name` raises
`AdapterNotImplementedError`. A future iteration may add the BCRA "central de
deudores" or OpenCorporates AR free tier for search.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

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
    RegistryIdentifier,
)

_CUIT_DIGITS_RE = re.compile(r"^\d{11}$")
# Mod-11 weights applied to the first 10 digits of the CUIT.
_CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
# Probe CUIT used by health_check — YPF S.A., always public.
_HEALTH_PROBE_CUIT = "30546689979"


def _normalize_cuit(value: str) -> str:
    cleaned = re.sub(r"[\s\-\.]", "", value or "")
    if not _CUIT_DIGITS_RE.match(cleaned):
        raise InvalidIdentifierError(f"CUIT must be 11 digits: {value}")
    total = sum(int(d) * w for d, w in zip(cleaned[:10], _CUIT_WEIGHTS))
    remainder = total % 11
    check = 0 if remainder == 0 else 11 - remainder
    # Edge case: a remainder of 1 produces a check digit of 10, which AFIP
    # handles by reassigning the entity type prefix — those CUITs simply don't
    # exist in practice, so a mismatch is a hard reject.
    if check == 10 or check != int(cleaned[10]):
        raise InvalidIdentifierError(f"CUIT checksum invalid: {value}")
    return cleaned


def _format_cuit(cuit: str) -> str:
    return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"


class ARAdapter(CountryAdapter):
    country_code = "AR"
    country_name = "Argentina"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    AFIP_PADRON_URL = "https://soa.afip.gob.ar/sr-padron/v2"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.AFIP_PADRON_URL) as client:
                resp = await get_with_retry(client, f"/persona/{_HEALTH_PROBE_CUIT}")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "AFIP padron supports identifier lookup only. Name search and "
                "filings (CNV listed-co reports) not yet wired."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "AFIP sr-padron does not expose name search; supply a CUIT to lookup_by_identifier."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"AR only supports VAT (CUIT) / COMPANY_NUMBER, got {id_type}"
            )
        cuit = _normalize_cuit(value)
        async with build_http_client(base_url=self.AFIP_PADRON_URL) as client:
            resp = await get_with_retry(client, f"/persona/{cuit}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                return None

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        # AFIP returns errors as {"success": false, "error": "..."} with HTTP 200.
        if payload.get("success") is False:
            return None
        return _details_from_padron(cuit, data)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # CNV publishes annual reports only for listed issuers, and the listing
        # is small (~100 firms). No free identifier-to-CNV-symbol mapping
        # exists, so for the MVP we return an empty list rather than scraping
        # cnv.gov.ar on every call. AFIP padron does not hold filings at all.
        return []


def _details_from_padron(cuit: str, data: dict[str, Any]) -> CompanyDetails:
    name = (
        data.get("razonSocial")
        or _name_from_person(data)
        or ""
    ).strip()

    legal_form = None
    tipo_persona = data.get("tipoPersona")
    if tipo_persona == "JURIDICA":
        legal_form = data.get("tipoClave") or "Persona Jurídica"
    elif tipo_persona == "FISICA":
        legal_form = "Persona Física"

    status = (data.get("estadoClave") or "").strip().lower() or None

    inc = _parse_date(data.get("fechaInscripcion") or data.get("fechaContratoSocial"))
    diss = _parse_date(data.get("fechaCierre") or data.get("fechaFallecimiento"))

    address = _address_from_padron(data)
    nace_codes = _activity_codes(data)

    identifiers = [
        RegistryIdentifier(type=IdentifierType.VAT, value=cuit, label="CUIT"),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=cuit, label="CUIT"
        ),
    ]

    return CompanyDetails(
        id=cuit,
        name=name,
        country="AR",
        legal_form=legal_form,
        status=status,
        incorporation_date=inc,
        dissolution_date=diss,
        registered_address=address,
        capital_amount=None,
        capital_currency="ARS",
        nace_codes=nace_codes,
        identifiers=identifiers,
        directors=[],
        raw=data,
        source_url=(
            "https://servicioscf.afip.gob.ar/publico/consultas/"
            f"consultaConstanciaAccion.aspx?cuit={cuit}"
        ),
    )


def _name_from_person(data: dict[str, Any]) -> str | None:
    nombre = (data.get("nombre") or "").strip()
    apellido = (data.get("apellido") or "").strip()
    full = f"{nombre} {apellido}".strip()
    return full or None


def _address_from_padron(data: dict[str, Any]) -> str | None:
    domicilios = data.get("domicilio") or []
    if not isinstance(domicilios, list) or not domicilios:
        return None
    # Prefer the fiscal domicile when present; AFIP marks it with tipoDomicilio.
    preferred = next(
        (d for d in domicilios if isinstance(d, dict) and (d.get("tipoDomicilio") or "").upper() == "FISCAL"),
        None,
    )
    d = preferred or next((x for x in domicilios if isinstance(x, dict)), None)
    if not d:
        return None
    parts = [
        d.get("direccion"),
        d.get("localidad"),
        d.get("descripcionProvincia") or d.get("provincia"),
        d.get("codPostal"),
    ]
    parts = [str(p).strip() for p in parts if p]
    return ", ".join(parts) or None


def _activity_codes(data: dict[str, Any]) -> list[str]:
    activities = data.get("actividad") or []
    if not isinstance(activities, list):
        return []
    codes: list[str] = []
    for a in activities:
        if not isinstance(a, dict):
            continue
        code = a.get("idActividad") or a.get("codigo")
        if code is not None:
            codes.append(str(code))
    return codes


def _parse_date(s: Any) -> date | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
