"""Italy adapter — VIES VAT + Borsa Italiana / CONSOB for listed firms.

Italy's authoritative registry is Registro Imprese (InfoCamere). Full filing
access is paid per query and explicitly out of scope for the free MVP. What
is free and usable:

- VIES (EU VAT Information Exchange) validates a Partita IVA and returns
  the registered name + address.
- Borsa Italiana publishes annual report links on its per-company pages;
  CONSOB tracks Italian listed issuers. Both are free for listed entities
  (Euronext Milan / Borsa Italiana).

So lookup_by_identifier hits VIES; fetch_financials surfaces Borsa Italiana
per-year pointers for entities we can detect as listed, and an empty list
otherwise. Name search is not possible from any free authoritative source —
raise to surface the gap.

Partita IVA format: 11 digits. First 7 identify the taxpayer, next 3 the
issuing tax office, and the 11th is a Luhn-style mod-10 check digit (odd
positions summed as-is; even positions doubled, with digits of any 2-digit
product summed individually).
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

_PIVA_RE = re.compile(r"^\d{11}$")

# Eni S.p.A. — stable, always-valid Partita IVA used as a liveness probe.
_VIES_HEALTH_PROBE = "00484960588"

_VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

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


def _normalize_piva(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("IT"):
        cleaned = cleaned[2:]
    if not _PIVA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Italian Partita IVA must be 11 digits: {value}"
        )
    if not _piva_checksum_ok(cleaned):
        raise InvalidIdentifierError(
            f"Italian Partita IVA checksum invalid: {value}"
        )
    return cleaned


def _piva_checksum_ok(piva: str) -> bool:
    """Validate Partita IVA mod-10 check digit (Luhn-style)."""
    total = 0
    for i, ch in enumerate(piva[:10]):
        n = int(ch)
        if i % 2 == 0:
            total += n
        else:
            doubled = n * 2
            total += doubled if doubled < 10 else doubled - 9
    check = (10 - (total % 10)) % 10
    return check == int(piva[10])


# Known Italian listed issuers we can deep-link into Borsa Italiana for. The
# canonical pivot for Borsa Italiana URLs is the ISIN, not the Partita IVA,
# so we maintain a small explicit map for the test universe. Extending this
# to every listed Italian issuer would require parsing the listed-companies
# index — a follow-up once the scraper pool lands.
_BORSA_ISIN_BY_PIVA: dict[str, str] = {
    "00484960588": "IT0003132476",  # Eni S.p.A.
    "00811720580": "IT0003128367",  # Enel S.p.A.
    "00799960158": "IT0000072618",  # Intesa Sanpaolo S.p.A.
    "00348170101": "IT0005239360",  # UniCredit S.p.A.
}


def _borsa_company_url(piva: str) -> str | None:
    isin = _BORSA_ISIN_BY_PIVA.get(piva)
    if not isin:
        return None
    return f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin}.html"


class ITAdapter(CountryAdapter):
    country_code = "IT"
    country_name = "Italy"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = _VIES_URL

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
                notes="VIES reachable but Eni Partita IVA reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via VIES; financials only for Borsa Italiana-listed "
                "firms. Name search unavailable from any free authoritative "
                "source (Registro Imprese is paid)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Italy has no free authoritative name-search API. Registro "
            "Imprese (InfoCamere) charges per query; VIES does not accept "
            "name queries. Use OpenCorporates global search or look up "
            "directly by Partita IVA."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"IT supports VAT/COMPANY_NUMBER, got {id_type}"
            )
        piva = _normalize_piva(value)
        vies = await self._vies_check(piva)
        if not vies or not vies.get("valid"):
            return None

        borsa_url = _borsa_company_url(piva)
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"IT{piva}", label="Partita IVA"
            ),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=piva,
                label="Codice Fiscale",
            ),
        ]
        return CompanyDetails(
            id=piva,
            name=(vies.get("name") or "").strip() or piva,
            country="IT",
            legal_form=None,
            status="active",
            registered_address=(vies.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": vies, "borsa_listed": bool(borsa_url)},
            source_url=borsa_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        piva = _normalize_piva(company_id)
        borsa_url = _borsa_company_url(piva)
        if not borsa_url:
            return []
        # Borsa Italiana publishes annual reports on each issuer's scheda
        # page; per-document URLs require parsing the page, which is a
        # follow-up once the scraper pool lands. Surface one entry per
        # recent year pointing at the durable scheda page so the LLM /
        # operator can deep-link in.
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(1, years + 1):
            year = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=piva,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="EUR",
                    structured_data=None,
                    document_url=borsa_url,
                    document_format="html",
                    source_url=borsa_url,
                )
            )
        return filings

    async def _vies_check(self, piva: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="IT", vat=piva)
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
    valid = (
        resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or ""
    ).lower() == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}
