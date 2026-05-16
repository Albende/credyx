"""Portugal adapter — VIES VAT validation + CMVM listed-company filings.

Portugal has no free authoritative name-search API. The Instituto dos
Registos e do Notariado (IRN / Registo Comercial Online) charges per
certificate, and Portal da Empresa exposes only an interactive web search
behind a CAPTCHA — neither qualifies as a free machine-readable source we
can wire in MVP.

What is free and usable:

- VIES (EU VAT Information Exchange) confirms a Portuguese NIPC is a
  valid VAT registration and returns the registered name + address.
- CMVM (Comissão do Mercado de Valores Mobiliários) publishes annual
  reports and other regulated disclosures for every Portuguese listed
  issuer at no cost. The public consultation page is durable and
  citable.

So `lookup_by_identifier` hits VIES and opportunistically attaches a
CMVM source URL when the entity has a listed-issuer page;
`fetch_financials` returns CMVM filing pointers for listed NIPCs and
an empty list otherwise. `search_by_name` raises to surface the gap.

NIPC format: 9 digits. Check digit (last) is computed from the first 8
digits with weights 9, 8, 7, 6, 5, 4, 3, 2; sum mod 11; if remainder is
0 or 1 the check digit is 0, else 11 - remainder.
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

_NIPC_RE = re.compile(r"^\d{9}$")

# EDP — Energias de Portugal, S.A.: a stable, always-valid NIPC used as a
# VIES liveness probe.
_VIES_HEALTH_PROBE = "500697256"


def _normalize_nipc(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("PT"):
        cleaned = cleaned[2:]
    if not _NIPC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Portuguese NIPC must be 9 digits: {value}"
        )
    if not _nipc_checksum_ok(cleaned):
        raise InvalidIdentifierError(f"Portuguese NIPC checksum invalid: {value}")
    return cleaned


def _nipc_checksum_ok(nipc: str) -> bool:
    weights = (9, 8, 7, 6, 5, 4, 3, 2)
    total = sum(int(nipc[i]) * weights[i] for i in range(8))
    remainder = total % 11
    expected = 0 if remainder < 2 else 11 - remainder
    return int(nipc[8]) == expected


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


class PTAdapter(CountryAdapter):
    country_code = "PT"
    country_name = "Portugal"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    CMVM_ENTITY_URL = "https://web3.cmvm.pt/sdi/emitentes/index.cfm"

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
                notes="VIES reachable but EDP NIPC reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via VIES; financials only for CMVM-listed issuers. "
                "Name search unavailable from any free authoritative source."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Portugal has no free authoritative name-search API. "
            "Registo Comercial Online charges per certificate and Portal da "
            "Empresa search is interactive only. Use OpenCorporates global "
            "search or look up directly by NIPC/VAT."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"PT supports VAT/COMPANY_NUMBER, got {id_type}"
            )
        nipc = _normalize_nipc(value)
        vies = await self._vies_check(nipc)
        if not vies or not vies.get("valid"):
            return None

        cmvm_listed = await self._cmvm_entity_exists(nipc)
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=nipc, label="NIPC"
            ),
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"PT{nipc}", label="VAT"
            ),
        ]
        return CompanyDetails(
            id=nipc,
            name=(vies.get("name") or "").strip() or nipc,
            country="PT",
            status="active",
            registered_address=(vies.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={
                "vies": vies,
                "cmvm_listed": cmvm_listed,
            },
            source_url=(
                f"{self.CMVM_ENTITY_URL}?dispatch=bynif&nif={nipc}"
                if cmvm_listed
                else None
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        nipc = _normalize_nipc(company_id)
        if not await self._cmvm_entity_exists(nipc):
            return []
        # CMVM exposes annual reports as PDF / iXBRL on each issuer's
        # disclosure page; the issuer page is the durable, citable URL.
        # We surface one filing entry per recent year pointing at the
        # issuer page so downstream operators can deep-link in. Per-doc
        # URLs need HTML parsing — wired in a follow-up once the PDF
        # extraction pipeline lands.
        page_url = f"{self.CMVM_ENTITY_URL}?dispatch=bynif&nif={nipc}"
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(1, years + 1):
            year = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=nipc,
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

    async def _vies_check(self, nipc: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="PT", vat=nipc)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }
        async with build_http_client(timeout=30.0, headers=headers) as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)

    async def _cmvm_entity_exists(self, nipc: str) -> bool:
        url = f"{self.CMVM_ENTITY_URL}?dispatch=bynif&nif={nipc}"
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(client, url)
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        body = resp.text.lower()
        # CMVM's CFM page returns 200 even for unknown NIPCs but renders a
        # "sem resultados" notice; presence of the canonical issuer detail
        # markers ("emitente", "nif") with no "sem resultados" string
        # signals a real listed issuer match.
        if "sem resultados" in body or "não foram encontrados" in body:
            return False
        return "emitente" in body or "nif" in body


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
        return {
            "valid": False,
            "fault": (fault.findtext("faultstring") or "").strip(),
        }
    resp = body.find("vies:checkVatResponse", _VIES_NS)
    if resp is None:
        return None
    valid = (
        resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or ""
    ).lower() == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}
