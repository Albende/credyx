"""Malta adapter — GLEIF + VIES + XBRL Filings Index.

Three free, authoritative sources usable without any API key. The old MBR
online system (registry.mbr.mt) migrated to a Wyzer SPA at
``register.mbr.mt`` / ``baros.mbr.mt`` whose company search now sits behind
an Azure B2C login, so it is no longer scrapeable key-free.

- GLEIF (https://api.gleif.org) — the free Global LEI index. Its golden-copy
  records carry the Maltese registry number ("C 2833") in ``entity.registeredAs``,
  the legal name, addresses, status and creation date. Used for name search
  and for company-number lookup. Coverage is limited to entities that hold an
  LEI (all listed / regulated companies plus a large slice of active SMEs).
- VIES (https://ec.europa.eu/taxation_customs/vies) — validates an MT VAT and
  returns the registered name + address; the cheapest reliable VAT resolution.
- XBRL Filings Index (https://filings.xbrl.org) — the public ESEF repository
  of EU listed-company annual financial reports. Every Malta-domiciled issuer
  files an iXBRL annual report here; each filing exposes a downloadable report
  package, keyed by LEI.

Identifier scope:
- COMPANY_NUMBER → "C" + 1–7 digits ("C 2833", "C2833", "2833" all valid).
- VAT             → MT + 8 digits.

Capabilities:
- search_by_name                       → GLEIF fuzzy legal-name search, MT-filtered.
- lookup_by_identifier(VAT)            → VIES SOAP.
- lookup_by_identifier(COMPANY_NUMBER) → GLEIF record whose registeredAs matches.
- fetch_financials                     → ESEF annual reports for the issuer's LEI.

We never fabricate registry or financial data — if a source has nothing for a
company, callers get an empty list or ``None``.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
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

_C_NUMBER_DIGITS_RE = re.compile(r"^\d{1,7}$")
_MT_VAT_RE = re.compile(r"^\d{8}$")
_LEI_RE = re.compile(r"^[A-Z0-9]{18}\d{2}$")

# Bank of Valletta — stable, always-valid MT VAT used as a VIES health probe.
_VIES_HEALTH_PROBE = "10172321"

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


def _normalize_company_number(value: str) -> str:
    """Return a canonical MT company number like "C2833"."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "")
    if cleaned.startswith("C"):
        cleaned = cleaned[1:]
    if not _C_NUMBER_DIGITS_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Malta company number must be 'C' + digits: {value}"
        )
    return f"C{cleaned}"


def _gleif_registered_as(cn: str) -> str:
    """GLEIF stores the MT number with a space ("C 2833")."""
    return f"C {cn[1:]}"


def _normalize_mt_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("MT"):
        cleaned = cleaned[2:]
    if not _MT_VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Malta VAT must be 'MT' + 8 digits: {value}"
        )
    return cleaned


class MTAdapter(CountryAdapter):
    country_code = "MT"
    country_name = "Malta"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
    FILINGS_BASE = "https://filings.xbrl.org"
    FILINGS_API = "https://filings.xbrl.org/api/filings"
    MBR_PORTAL = "https://baros.mbr.mt/app/query/search_for_company"

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
                notes="VIES reachable but Bank of Valletta VAT reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + company-number lookup via GLEIF, VAT via VIES, "
                "financials via the ESEF filings.xbrl.org index. All key-free; "
                "coverage limited to LEI-holding / listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        records = await self._gleif_query(
            {
                "filter[entity.legalName]": name,
                "filter[entity.legalAddress.country]": "MT",
                "page[size]": str(min(max(limit, 1), 50)),
            }
        )
        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for rec in records:
            match = _gleif_record_to_match(rec)
            if match is None or match.id in seen:
                continue
            seen.add(match.id)
            matches.append(match)
        return matches[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_company_number(value)
        raise InvalidIdentifierError(
            f"MT supports COMPANY_NUMBER or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        lei = await self._resolve_lei(company_id)
        if lei is None:
            return []
        cn = None if _LEI_RE.match(company_id.strip().upper()) else _normalize_company_number(company_id)
        filings = await self._esef_filings(lei)
        filings.sort(key=lambda f: f["period_end"], reverse=True)
        out: list[FinancialFiling] = []
        for f in filings[:years]:
            period_end = _parse_iso_date(f["period_end"])
            if period_end is None:
                continue
            out.append(
                FinancialFiling(
                    company_id=cn or lei,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="EUR",
                    structured_data=None,
                    document_url=f"{self.FILINGS_BASE}{f['package_url']}",
                    document_format="xbrl",
                    source_url=f"{self.FILINGS_BASE}{f['viewer_url']}",
                )
            )
        return out

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_mt_vat(value)
        result = await self._vies_check(vat)
        if not result or not result.get("valid"):
            return None
        return CompanyDetails(
            id=f"MT{vat}",
            name=(result.get("name") or "").strip() or f"MT{vat}",
            country="MT",
            status="active",
            registered_address=(result.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=f"MT{vat}", label="VAT"),
            ],
            raw={"vies": result},
            source_url=None,
        )

    async def _lookup_by_company_number(self, value: str) -> CompanyDetails | None:
        cn = _normalize_company_number(value)
        records = await self._gleif_query(
            {
                "filter[entity.registeredAs]": _gleif_registered_as(cn),
                "filter[entity.legalAddress.country]": "MT",
            }
        )
        rec = _pick_record_by_registered_as(records, cn)
        if rec is None:
            return None
        attrs = rec["attributes"]
        entity = attrs["entity"]
        lei = attrs["lei"]
        return CompanyDetails(
            id=cn,
            name=(entity["legalName"]["name"] or "").strip() or cn,
            country="MT",
            legal_form=(entity.get("legalForm") or {}).get("id"),
            status=_map_status(entity.get("status")),
            incorporation_date=_parse_iso_date(entity.get("creationDate")),
            registered_address=_format_gleif_address(entity.get("legalAddress")),
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=cn, label="Company Number"
                ),
                RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI"),
            ],
            raw={"gleif": attrs},
            source_url=f"https://search.gleif.org/#/record/{lei}",
        )

    async def _resolve_lei(self, company_id: str) -> str | None:
        candidate = company_id.strip().upper()
        if _LEI_RE.match(candidate):
            return candidate
        cn = _normalize_company_number(company_id)
        records = await self._gleif_query(
            {
                "filter[entity.registeredAs]": _gleif_registered_as(cn),
                "filter[entity.legalAddress.country]": "MT",
            }
        )
        rec = _pick_record_by_registered_as(records, cn)
        return rec["attributes"]["lei"] if rec is not None else None

    async def _gleif_query(self, params: dict[str, str]) -> list[dict[str, Any]]:
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.GLEIF_URL, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        try:
            return resp.json().get("data", [])
        except ValueError:
            return []

    async def _esef_filings(self, lei: str) -> list[dict[str, Any]]:
        params = {
            "filter": f'[{{"name":"entity.identifier","op":"eq","val":"{lei}"}}]',
            "page[size]": "50",
        }
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.FILINGS_API, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json().get("data", [])
        except ValueError:
            return []
        out: list[dict[str, Any]] = []
        for item in data:
            attrs = item.get("attributes") or {}
            if attrs.get("period_end") and attrs.get("package_url"):
                out.append(attrs)
        return out

    async def _vies_check(self, vat: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="MT", vat=vat)
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


_STATUS_MAP = {
    "ACTIVE": "active",
    "INACTIVE": "inactive",
    "NULL": None,
}


def _map_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    return _STATUS_MAP.get(raw.upper(), raw.lower())


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _format_gleif_address(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts: list[str] = []
    parts.extend(line for line in (addr.get("addressLines") or []) if line)
    for key in ("city", "postalCode"):
        val = addr.get(key)
        if val:
            parts.append(val)
    return ", ".join(parts) or None


def _gleif_record_to_match(rec: dict[str, Any]) -> CompanyMatch | None:
    attrs = rec.get("attributes") or {}
    entity = attrs.get("entity") or {}
    lei = attrs.get("lei")
    name = ((entity.get("legalName") or {}).get("name") or "").strip()
    if not lei or not name:
        return None
    registered_as = (entity.get("registeredAs") or "").strip()
    cn = None
    if registered_as:
        digits = re.sub(r"\D", "", registered_as)
        if registered_as.upper().startswith("C") and digits:
            cn = f"C{digits}"
    identifiers = [RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")]
    if cn:
        identifiers.insert(
            0,
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=cn, label="Company Number"
            ),
        )
    return CompanyMatch(
        id=cn or lei,
        name=name,
        country="MT",
        identifiers=identifiers,
        address=_format_gleif_address(entity.get("legalAddress")),
        status=_map_status(entity.get("status")),
        source_url=f"https://search.gleif.org/#/record/{lei}",
    )


def _pick_record_by_registered_as(
    records: list[dict[str, Any]], cn: str
) -> dict[str, Any] | None:
    for rec in records:
        registered_as = ((rec.get("attributes") or {}).get("entity") or {}).get(
            "registeredAs"
        ) or ""
        if re.sub(r"\D", "", registered_as) == cn[1:]:
            return rec
    return records[0] if len(records) == 1 else None


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
