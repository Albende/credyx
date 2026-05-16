"""Latvia adapter — Uzņēmumu reģistrs (UR) open data + VIES.

Free, public Latvian sources usable without a paid license:

- data.gov.lv publishes the full Enterprise Register (UR) of Latvia as
  open data under https://data.gov.lv/dati/lv/dataset/uz. The most useful
  resource is ``register.csv`` listing every legal entity with its
  ``regcode`` (11-digit registration number), name, legal form, address,
  registration date and status. We stream the CSV on demand and filter
  in-memory — there is no per-company JSON endpoint on the open-data
  portal.
- VIES is the cheapest way to resolve an LV VAT (LV + 11 digits) to a
  name + registered address.
- Annual reports are filed to UR but the full PDF extracts are paid via
  Lursoft and are out of scope per project rules. ``fetch_financials``
  therefore returns no documents — never mock data.

Identifier scope:
- COMPANY_NUMBER → ``reģistrācijas numurs``, 11 digits.
- VAT             → ``LV`` + 11 digits.

If the open-data CSV becomes unreachable or its schema changes, callers
see the underlying httpx error or an empty result — we never fabricate
registry data.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_REGCODE_RE = re.compile(r"^\d{11}$")
_LV_VAT_RE = re.compile(r"^\d{11}$")

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


def _normalize_regcode(value: str) -> str:
    """Return a canonical 11-digit Latvian reģistrācijas numurs."""
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("LV"):
        cleaned = cleaned[2:]
    if not _REGCODE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Latvian reģistrācijas numurs must be 11 digits: {value}"
        )
    return cleaned


def _normalize_lv_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("LV"):
        cleaned = cleaned[2:]
    if not _LV_VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Latvian VAT must be 'LV' + 11 digits: {value}"
        )
    return cleaned


class LVAdapter(CountryAdapter):
    country_code = "LV"
    country_name = "Latvia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    # The UR "register" dataset on data.gov.lv. The CKAN-resolved CSV
    # download URL has been stable since 2014; if the portal changes it,
    # set LV_UR_REGISTER_CSV_URL to override at deploy time.
    REGISTER_CSV_URL = (
        "https://data.gov.lv/dati/dataset/0c5e1a3b-0097-45a9-afa9-7f7aaded71a0/"
        "resource/25e80bf3-f107-4ab4-89ef-251b5b9374e9/download/register.csv"
    )
    UR_PUBLIC_PAGE = "https://www.ur.gov.lv/lv/uznemumu-meklesana/"

    async def health_check(self) -> AdapterHealth:
        # VIES is the only live probe we can run without downloading a large
        # CSV. A successful (or even cleanly invalid) VIES round-trip means
        # the network path is good; we don't require a valid hit here.
        try:
            async with self._vies_client() as client:
                resp = await client.post(
                    self.VIES_URL,
                    content=_VIES_ENVELOPE.format(cc="LV", vat="40003032949"),
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES returned HTTP {resp.status_code}.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search/lookup via data.gov.lv UR open-data CSV; VAT via VIES. "
                "Annual report PDFs are paid via Lursoft and not exposed here."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = (name or "").strip().lower()
        if not needle:
            return []
        try:
            rows = await self._fetch_register_csv()
        except httpx.HTTPError:
            return []
        matches: list[CompanyMatch] = []
        for row in rows:
            row_name = (row.get("name") or "").strip()
            if not row_name or needle not in row_name.lower():
                continue
            regcode = (row.get("regcode") or "").strip()
            if not regcode:
                continue
            matches.append(_match_from_row(regcode, row_name, row))
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_regcode(value)
        raise InvalidIdentifierError(
            f"LV supports COMPANY_NUMBER (reģistrācijas numurs) or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Validate the identifier so callers get a clear error for garbage
        # input, then return an empty list — UR annual reports are paid
        # Lursoft extracts and we never invent filings.
        _normalize_regcode(company_id)
        return []

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_lv_vat(value)
        result = await self._vies_check(vat)
        if not result or not result.get("valid"):
            return None
        identifiers = [
            RegistryIdentifier(type=IdentifierType.VAT, value=f"LV{vat}", label="PVN numurs"),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=vat,
                label="Reģistrācijas numurs",
            ),
        ]
        return CompanyDetails(
            id=f"LV{vat}",
            name=(result.get("name") or "").strip() or f"LV{vat}",
            country="LV",
            status="active",
            registered_address=(result.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": result},
            source_url=None,
        )

    async def _lookup_by_regcode(self, value: str) -> CompanyDetails | None:
        regcode = _normalize_regcode(value)
        try:
            rows = await self._fetch_register_csv()
        except httpx.HTTPError:
            return None
        for row in rows:
            if (row.get("regcode") or "").strip() == regcode:
                return _details_from_row(regcode, row)
        return None

    async def _fetch_register_csv(self) -> list[dict[str, str]]:
        """Stream the UR open-data CSV and return its rows as dicts.

        The dataset is small enough (a few tens of MB) to hold in memory
        for the request lifetime; the API caches structured lookup
        results in Postgres so this isn't fetched on every call.
        """
        async with build_http_client(timeout=120.0) as client:
            resp = await get_with_retry(client, self.REGISTER_CSV_URL)
            resp.raise_for_status()
            text = resp.text
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        return [_normalize_row(r) for r in reader]

    async def _vies_check(self, vat: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="LV", vat=vat)
        async with self._vies_client() as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)

    def _vies_client(self) -> httpx.AsyncClient:
        return build_http_client(
            timeout=30.0,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        )


# data.gov.lv occasionally varies column casing across snapshots; normalize
# the keys we care about to a stable lower-case set.
_COLUMN_ALIASES: dict[str, str] = {
    "regcode": "regcode",
    "regcods": "regcode",
    "regnumber": "regcode",
    "regnr": "regcode",
    "name": "name",
    "name_before_quotes": "name_short",
    "sepa": "name_short",
    "name_in_quotes": "name_short",
    "type": "legal_form",
    "type_text": "legal_form",
    "registered": "registered",
    "registration_date": "registered",
    "terminated": "terminated",
    "address": "address",
    "addresses": "address",
    "address_full": "address",
    "index": "postal_code",
    "addresses_index": "postal_code",
}


def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        norm_key = _COLUMN_ALIASES.get(key.strip().lower(), key.strip().lower())
        if value is None:
            continue
        # First non-empty value wins so aliases don't overwrite real columns.
        if norm_key not in out or not out[norm_key]:
            out[norm_key] = value.strip()
    return out


def _match_from_row(regcode: str, row_name: str, row: dict[str, str]) -> CompanyMatch:
    return CompanyMatch(
        id=regcode,
        name=row_name,
        country="LV",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=regcode,
                label="Reģistrācijas numurs",
            )
        ],
        address=_address_from_row(row),
        status=_status_from_row(row),
        source_url=f"https://www.lursoft.lv/lapas/{regcode}/",
    )


def _details_from_row(regcode: str, row: dict[str, str]) -> CompanyDetails:
    name = (row.get("name") or row.get("name_short") or "").strip()
    return CompanyDetails(
        id=regcode,
        name=name or regcode,
        country="LV",
        legal_form=(row.get("legal_form") or "").strip() or None,
        status=_status_from_row(row),
        registered_address=_address_from_row(row),
        capital_currency="EUR",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=regcode,
                label="Reģistrācijas numurs",
            ),
        ],
        raw={"ur_row": row},
        source_url=f"https://www.lursoft.lv/lapas/{regcode}/",
    )


def _address_from_row(row: dict[str, str]) -> str | None:
    parts = [row.get("address"), row.get("postal_code")]
    joined = ", ".join(p.strip() for p in parts if p and p.strip())
    return joined or None


def _status_from_row(row: dict[str, str]) -> str | None:
    terminated = (row.get("terminated") or "").strip()
    if terminated:
        return f"terminated:{terminated}"
    if (row.get("registered") or "").strip():
        return "active"
    return None


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
