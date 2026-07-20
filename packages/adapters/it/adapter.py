"""Italy adapter — GLEIF + VIES + filings.xbrl.org (ESEF).

Italy's authoritative registry is Registro Imprese (InfoCamere). Full filing
access is paid per query and out of scope for the free MVP. The free,
key-less sources that give real, live data:

- **GLEIF** (Global Legal Entity Identifier Foundation) — free JSON:API.
  Name search returns Italian entities with their LEI and the Registro
  Imprese registration number (``registeredAs`` = Partita IVA / Codice
  Fiscale). This is the name-search + LEI-mapping backbone.
- **VIES** (EU VAT Information Exchange) — validates a Partita IVA and
  returns the officially registered name + address.
- **filings.xbrl.org** — the XBRL International index of ESEF annual
  financial reports that every EU-listed issuer must file since 2021.
  Keyed by LEI; returns downloadable iXBRL reports. This is where real,
  per-company filed financials come from for listed Italian issuers.

So: ``search_by_name`` → GLEIF; ``lookup_by_identifier`` → VIES (enriched
with GLEIF LEI); ``fetch_financials`` → Partita IVA → GLEIF LEI →
filings.xbrl.org ESEF reports. Unlisted entities have no free filed
accounts (Registro Imprese is paid) and return an empty list.

Partita IVA format: 11 digits. First 7 identify the taxpayer, next 3 the
issuing tax office, and the 11th is a Luhn-style mod-10 check digit (odd
positions summed as-is; even positions doubled, with digits of any 2-digit
product summed individually).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_PIVA_RE = re.compile(r"^\d{11}$")
_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")

# Eni S.p.A. — stable, always-valid Partita IVA used as a liveness probe.
_VIES_HEALTH_PROBE = "00484960588"

_VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

_GLEIF_BASE = "https://api.gleif.org/api/v1/lei-records"
_GLEIF_HEADERS = {"Accept": "application/vnd.api+json"}

# Registro Imprese registration authority id inside GLEIF. Used to prefer the
# Italian commercial-register number when an entity carries several ids.
_RA_REGISTRO_IMPRESE = "RA000407"

_FILINGS_BASE = "https://filings.xbrl.org"
_FILINGS_API = f"{_FILINGS_BASE}/api/filings"

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


def _format_gleif_address(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts = list(addr.get("addressLines") or [])
    for key in ("postalCode", "city", "region", "country"):
        val = addr.get(key)
        if val:
            parts.append(str(val))
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _gleif_identifiers(entity: dict[str, Any], lei: str) -> list[RegistryIdentifier]:
    identifiers = [
        RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI"),
    ]
    registered_as = (entity.get("registeredAs") or "").strip()
    if _PIVA_RE.match(registered_as):
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=f"IT{registered_as}",
                label="Partita IVA",
            )
        )
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=registered_as,
                label="Codice Fiscale",
            )
        )
    elif registered_as:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.OTHER,
                value=registered_as,
                label="Registro Imprese id",
            )
        )
    return identifiers


def _build_details(
    piva: str | None,
    gleif: dict[str, Any] | None,
    lei: str,
    vies: dict[str, Any] | None,
) -> CompanyDetails:
    entity = (gleif or {}).get("entity") or {}
    vies_name = ((vies or {}).get("name") or "").strip()
    gleif_name = ((entity.get("legalName") or {}).get("name") or "").strip()
    vies_address = ((vies or {}).get("address") or "").strip()

    identifiers: list[RegistryIdentifier] = []
    if piva:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"IT{piva}", label="Partita IVA"
            )
        )
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=piva,
                label="Codice Fiscale",
            )
        )
    if lei:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
        )

    legal_form = None
    legal_form_id = (entity.get("legalForm") or {}).get("id")
    if legal_form_id:
        legal_form = str(legal_form_id)

    source_url = (
        f"https://search.gleif.org/#/record/{lei}"
        if lei
        else "https://ec.europa.eu/taxation_customs/vies/"
    )
    return CompanyDetails(
        id=piva or lei,
        name=vies_name or gleif_name or piva or lei,
        country="IT",
        legal_form=legal_form,
        status=(entity.get("status") or "").lower() or "active",
        registered_address=vies_address
        or _format_gleif_address(entity.get("legalAddress")),
        capital_currency="EUR",
        identifiers=identifiers,
        raw={"vies": vies, "gleif_lei": lei or None},
        source_url=source_url,
    )


class ITAdapter(CountryAdapter):
    country_code = "IT"
    country_name = "Italy"
    identifier_types = [
        IdentifierType.VAT,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.LEI,
    ]
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
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if not payload or not payload.get("valid"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="VIES reachable but Eni Partita IVA reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search via GLEIF; lookup via VIES (+GLEIF LEI); filed "
                "financials via filings.xbrl.org ESEF for listed issuers. "
                "Registro Imprese filings for unlisted firms are paid — "
                "unlisted fetch_financials returns []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            raise InvalidIdentifierError("Empty company name")
        records = await self._gleif_search(
            {
                "filter[entity.legalName]": query,
                "filter[entity.legalAddress.country]": "IT",
            },
            limit=limit,
        )
        if not records:
            raise AdapterNotImplementedError(
                f"No GLEIF-registered Italian entity matched '{name}'. GLEIF "
                "covers entities that hold an LEI; smaller firms without one "
                "are only in the paid Registro Imprese."
            )
        matches: list[CompanyMatch] = []
        for rec in records:
            attrs = rec.get("attributes") or {}
            entity = attrs.get("entity") or {}
            lei = attrs.get("lei") or rec.get("id") or ""
            legal_name = ((entity.get("legalName") or {}).get("name") or "").strip()
            registered_as = (entity.get("registeredAs") or "").strip()
            local_id = registered_as if _PIVA_RE.match(registered_as) else lei
            matches.append(
                CompanyMatch(
                    id=local_id,
                    name=legal_name or local_id,
                    country="IT",
                    identifiers=_gleif_identifiers(entity, lei),
                    address=_format_gleif_address(entity.get("legalAddress")),
                    status=(entity.get("status") or "").lower() or None,
                    source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (
            IdentifierType.VAT,
            IdentifierType.COMPANY_NUMBER,
            IdentifierType.LEI,
        ):
            raise InvalidIdentifierError(
                f"IT supports VAT/COMPANY_NUMBER/LEI, got {id_type}"
            )

        if id_type is IdentifierType.LEI:
            lei = value.strip().upper()
            if not _LEI_RE.match(lei):
                raise InvalidIdentifierError(
                    f"LEI must be 20 alphanumeric characters: {value}"
                )
            gleif = await self._gleif_by_lei(lei)
            if gleif is None:
                return None
            piva = ((gleif.get("entity") or {}).get("registeredAs") or "").strip()
            vies = await self._vies_check_safe(piva) if _PIVA_RE.match(piva) else None
            return _build_details(piva or None, gleif, lei, vies)

        piva = _normalize_piva(value)
        gleif = await self._gleif_by_registered_as(piva)
        vies = await self._vies_check_safe(piva)

        if (not vies or not vies.get("valid")) and gleif is None:
            return None

        lei = (gleif or {}).get("lei") or ""
        return _build_details(piva, gleif, lei, vies)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raw_id = company_id.strip().upper()
        if _LEI_RE.match(raw_id) and not _PIVA_RE.match(raw_id):
            lei = raw_id
            anchor = raw_id
        else:
            piva = _normalize_piva(company_id)
            gleif = await self._gleif_by_registered_as(piva)
            lei = (gleif or {}).get("lei")
            anchor = piva
        if not lei:
            return []

        filings_raw = await self._filings_by_lei(lei)
        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for item in filings_raw:
            attrs = item.get("attributes") or {}
            period_end = attrs.get("period_end")
            if not period_end:
                continue
            try:
                pe = date.fromisoformat(period_end)
            except ValueError:
                continue
            if pe.year in seen_years:
                continue
            seen_years.add(pe.year)

            report_url = attrs.get("report_url")
            document_url = f"{_FILINGS_BASE}{report_url}" if report_url else None
            viewer_url = attrs.get("viewer_url")
            source_url = (
                f"{_FILINGS_BASE}{viewer_url}" if viewer_url else _FILINGS_API
            )
            filings.append(
                FinancialFiling(
                    company_id=anchor,
                    year=pe.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=pe,
                    currency="EUR",
                    structured_data=None,
                    document_url=document_url,
                    document_format="xbrl",
                    source_url=source_url,
                )
            )

        filings.sort(key=lambda f: f.year, reverse=True)
        return filings[:years]

    async def _gleif_search(
        self, filters: dict[str, str], *, limit: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = dict(filters)
        params["page[size]"] = min(max(limit, 1), 50)
        async with build_http_client(
            timeout=30.0, headers=_GLEIF_HEADERS
        ) as client:
            resp = await get_with_retry(client, _GLEIF_BASE, params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("data") or []

    async def _gleif_by_registered_as(self, piva: str) -> dict[str, Any] | None:
        records = await self._gleif_search(
            {
                "filter[entity.registeredAs]": piva,
                "filter[entity.legalAddress.country]": "IT",
            },
            limit=5,
        )
        best: dict[str, Any] | None = None
        for rec in records:
            attrs = rec.get("attributes") or {}
            entity = attrs.get("entity") or {}
            if best is None:
                best = attrs
            registered_at = (entity.get("registeredAt") or {}).get("id")
            if registered_at == _RA_REGISTRO_IMPRESE:
                return attrs
        return best

    async def _gleif_by_lei(self, lei: str) -> dict[str, Any] | None:
        async with build_http_client(
            timeout=30.0, headers=_GLEIF_HEADERS
        ) as client:
            resp = await get_with_retry(client, f"{_GLEIF_BASE}/{lei}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data")
        if not data:
            return None
        return data.get("attributes")

    async def _filings_by_lei(self, lei: str) -> list[dict[str, Any]]:
        filter_expr = json.dumps(
            [{"name": "entity.identifier", "op": "eq", "val": lei}]
        )
        params = {
            "filter": filter_expr,
            "sort": "-period_end",
            "page[size]": 20,
        }
        async with build_http_client(
            timeout=30.0, headers=_GLEIF_HEADERS
        ) as client:
            resp = await get_with_retry(client, _FILINGS_API, params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("data") or []

    async def _vies_check_safe(self, piva: str) -> dict[str, Any] | None:
        try:
            return await self._vies_check(piva)
        except Exception:
            return None

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
