"""Spain adapter — VIES VAT + CNMV listed-company filings.

Spain has no free official API for the Registro Mercantil; filed annual
accounts for private companies sit behind paid InfoCamere-style services we
explicitly refuse to integrate. What is free and usable:

- VIES (EU VAT Information Exchange) confirms a CIF/NIF is a valid Spanish
  VAT registration and returns the registered name + address.
- CNMV (Comisión Nacional del Mercado de Valores) publishes annual reports
  and XBRL filings for every Spanish listed company at no cost.

So lookup_by_identifier hits VIES then opportunistically attaches CNMV
filing pointers when the entity is listed; fetch_financials returns CNMV
filings for listed CIFs and an empty list otherwise. Name search is not
possible from any free authoritative source — raise to surface the gap.

CIF format: leading letter (organisation class) + 7 digits + check char
(letter or digit). The check character is computed from the 7-digit body.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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

_CIF_RE = re.compile(r"^[A-HJ-NP-SUVW]\d{7}[0-9A-J]$")
_CIF_CHECK_LETTERS = "JABCDEFGHI"
_CIF_LETTER_REQUIRES_LETTER_CHECK = set("PQRSNW")
_CIF_LETTER_REQUIRES_DIGIT_CHECK = set("ABEH")

_VIES_HEALTH_PROBE = "A28015865"  # Telefónica — stable, always-valid CIF


def _normalize_cif(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("ES"):
        cleaned = cleaned[2:]
    if not _CIF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Spanish CIF/NIF must be letter + 7 digits + check char: {value}"
        )
    if not _cif_checksum_ok(cleaned):
        raise InvalidIdentifierError(f"Spanish CIF/NIF checksum invalid: {value}")
    return cleaned


def _cif_checksum_ok(cif: str) -> bool:
    """Validate the Spanish CIF check character.

    Algorithm: doubling odd-positioned digits (1-indexed from the body),
    summing tens+units of each product, adding even-positioned digits, taking
    the last digit of the total, then 10 - that digit mod 10. Map to a digit
    or to a letter from `_CIF_CHECK_LETTERS` depending on the org-class
    letter.
    """
    body = cif[1:8]
    given = cif[8]
    odd_sum = 0
    even_sum = 0
    for i, ch in enumerate(body, start=1):
        n = int(ch)
        if i % 2 == 1:
            doubled = n * 2
            odd_sum += (doubled // 10) + (doubled % 10)
        else:
            even_sum += n
    total = odd_sum + even_sum
    control_digit = (10 - (total % 10)) % 10
    control_letter = _CIF_CHECK_LETTERS[control_digit]
    org_letter = cif[0]
    if org_letter in _CIF_LETTER_REQUIRES_LETTER_CHECK:
        return given == control_letter
    if org_letter in _CIF_LETTER_REQUIRES_DIGIT_CHECK:
        return given.isdigit() and int(given) == control_digit
    return given == str(control_digit) or given == control_letter


_VIES_ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:checkVat>
      <urn:countryCode>{cc}</urn:countryCode>
      <urn:vatNumber>{vat}</urn:vatNumber>
    </urn:checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""

_VIES_NS = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "vies": "urn:ec.europa.eu:taxud:vies:services:checkVat:types",
}


class ESAdapter(CountryAdapter):
    country_code = "ES"
    country_name = "Spain"
    identifier_types = [IdentifierType.CIF, IdentifierType.NIF, IdentifierType.VAT]
    primary_identifier = IdentifierType.CIF
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    CNMV_ENTITY_URL = (
        "https://www.cnmv.es/Portal/Consultas/EE/InformacionEntidad.aspx"
    )

    async def health_check(self) -> AdapterHealth:
        try:
            payload = await self._vies_check(_VIES_HEALTH_PROBE)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if not payload or not payload.get("valid"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="VIES reachable but Telefónica CIF reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via VIES; financials only for CNMV-listed firms. "
                "Name search unavailable from any free authoritative source."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Spain has no free authoritative name-search API. "
            "Registro Mercantil charges per query; BORME publishes daily PDFs "
            "without a name index. Use OpenCorporates global search or look up "
            "directly by CIF/NIF/VAT."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (
            IdentifierType.CIF,
            IdentifierType.NIF,
            IdentifierType.VAT,
        ):
            raise InvalidIdentifierError(
                f"ES supports CIF/NIF/VAT, got {id_type}"
            )
        cif = _normalize_cif(value)
        vies = await self._vies_check(cif)
        if not vies or not vies.get("valid"):
            return None

        cnmv_listed = await self._cnmv_entity_exists(cif)
        identifiers = [
            RegistryIdentifier(type=IdentifierType.CIF, value=cif, label="CIF"),
            RegistryIdentifier(type=IdentifierType.VAT, value=f"ES{cif}", label="VAT"),
        ]
        return CompanyDetails(
            id=cif,
            name=(vies.get("name") or "").strip() or cif,
            country="ES",
            legal_form=_legal_form_from_cif_letter(cif[0]),
            status="active",
            registered_address=(vies.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={
                "vies": vies,
                "cnmv_listed": cnmv_listed,
            },
            source_url=(
                f"{self.CNMV_ENTITY_URL}?nif={cif}" if cnmv_listed else None
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cif = _normalize_cif(company_id)
        if not await self._cnmv_entity_exists(cif):
            return []
        # CNMV exposes annual reports as PDF/XBRL on the entity page itself;
        # the listing page is the durable, citable URL. We surface one filing
        # entry per recent year pointing at the entity page so the LLM /
        # operator can deep-link in. Real per-document URLs require parsing
        # the entity page's HTML — pulled in a follow-up once the PDF
        # extraction pipeline lands.
        page_url = f"{self.CNMV_ENTITY_URL}?nif={cif}"
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(1, years + 1):
            year = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=cif,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="EUR",
                    structured_data=None,
                    document_url=page_url,
                    document_format="html",
                    source_url=page_url,
                )
            )
        return filings

    async def _vies_check(self, cif: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="ES", vat=cif)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }
        async with build_http_client(timeout=30.0, headers=headers) as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code >= 500:
                resp.raise_for_status()
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)

    async def _cnmv_entity_exists(self, cif: str) -> bool:
        url = f"{self.CNMV_ENTITY_URL}?nif={cif}"
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(client, url)
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        body = resp.text.lower()
        # CNMV returns 200 even when the CIF is unknown but renders a
        # "no se ha encontrado" notice; presence of the canonical entity
        # heading distinguishes a real match.
        if "no se ha encontrado" in body or "no se han encontrado" in body:
            return False
        return "informacionentidad" in body or "denominaci" in body


def _parse_vies_response(xml_text: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    body = root.find("soap:Body", _VIES_NS)
    if body is None:
        return None
    fault = body.find("soap:Fault", _VIES_NS)
    if fault is not None:
        return {"valid": False, "fault": (fault.findtext("faultstring") or "").strip()}
    resp = body.find("vies:checkVatResponse", _VIES_NS)
    if resp is None:
        return None
    valid = (resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or "").lower() == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}


def _legal_form_from_cif_letter(letter: str) -> str | None:
    return {
        "A": "Sociedad Anónima",
        "B": "Sociedad de Responsabilidad Limitada",
        "C": "Sociedad Colectiva",
        "D": "Sociedad Comanditaria",
        "E": "Comunidad de Bienes",
        "F": "Sociedad Cooperativa",
        "G": "Asociación",
        "H": "Comunidad de Propietarios",
        "J": "Sociedad Civil",
        "P": "Corporación Local",
        "Q": "Organismo Público",
        "R": "Congregación Religiosa",
        "S": "Órgano de la Administración",
        "U": "Unión Temporal de Empresas",
        "V": "Otros tipos",
        "N": "Entidad Extranjera",
        "W": "Establecimiento Permanente de Entidad No Residente",
    }.get(letter.upper())
