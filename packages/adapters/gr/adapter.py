"""Greece adapter — GEMI publicity portal + VIES VAT.

Two complementary free sources:

- GEMI (Geniko Emporiko Mitroo, General Commercial Registry) is the
  official corporate registry. Its public-disclosure portal at
  https://publicity.businessportal.gr/ serves a JSON-backed search and
  detail surface (paths may shift; we tolerate response-shape drift).
- VIES (EU VAT Information Exchange) covers ΑΦΜ lookups under the EL
  country prefix and returns the registered legal name + address.

ATHEX (Athens Exchange) hosts free PDF annual reports for listed
companies. Index discovery is brittle and outside the MVP scope — we
return `[]` from `fetch_financials` and surface the ATHEX entity URL on
the `CompanyDetails.raw` payload for listed firms when we can detect
them.

Identifiers:

- GEMI number: 9 digits (some legacy records use up to 12 — accept both,
  primary format is 9). Type: `COMPANY_NUMBER`.
- ΑΦΜ (VAT): 9 digits. EU prefix is "EL" (NOT "GR"). Type: `VAT`.

ΑΦΜ checksum: weights 256, 128, 64, 32, 16, 8, 4, 2 over digits 1-8
(left-to-right, MSB-first), sum mod 11; the check digit is that mod, or
0 if it equals 10. The check digit is the 9th digit of the ΑΦΜ.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
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

_AFM_RE = re.compile(r"^\d{9}$")
_GEMI_RE = re.compile(r"^\d{9,12}$")
_AFM_WEIGHTS = (256, 128, 64, 32, 16, 8, 4, 2)

_VIES_URL = (
    "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
)
_VIES_HEALTH_PROBE_AFM = "094019245"  # OTE — stable, always-valid ΑΦΜ
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


def _normalize_afm(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("EL") or cleaned.startswith("GR"):
        cleaned = cleaned[2:]
    if not _AFM_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Greek ΑΦΜ must be 9 digits (optional EL/GR prefix): {value}"
        )
    if not _afm_checksum_ok(cleaned):
        raise InvalidIdentifierError(f"Greek ΑΦΜ checksum invalid: {value}")
    return cleaned


def _afm_checksum_ok(afm: str) -> bool:
    body = afm[:8]
    given = int(afm[8])
    total = sum(int(d) * w for d, w in zip(body, _AFM_WEIGHTS))
    expected = total % 11
    if expected == 10:
        expected = 0
    return expected == given


def _normalize_gemi(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _GEMI_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"GEMI number must be 9-12 digits: {value}"
        )
    return cleaned


class GRAdapter(CountryAdapter):
    country_code = "GR"
    country_name = "Greece"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    GEMI_BASE_URL = "https://publicity.businessportal.gr"
    ATHEX_ENTITY_URL = "https://www.athexgroup.gr/web/guest/companies-financial-data"

    async def health_check(self) -> AdapterHealth:
        gemi_reachable = False
        try:
            async with build_http_client(base_url=self.GEMI_BASE_URL, timeout=15.0) as client:
                resp = await get_with_retry(client, "/")
                gemi_reachable = resp.status_code < 500
        except Exception:
            gemi_reachable = False

        vies_ok = False
        try:
            payload = await self._vies_check(_VIES_HEALTH_PROBE_AFM)
            vies_ok = bool(payload and payload.get("valid"))
        except Exception:
            vies_ok = False

        if not gemi_reachable and not vies_ok:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Both GEMI publicity portal and VIES unreachable.",
            )
        if gemi_reachable and vies_ok:
            status = AdapterStatus.OK
            notes = (
                "GEMI publicity portal + VIES reachable. Financials available "
                "only for ATHEX-listed firms via free PDF index (not wired)."
            )
        else:
            status = AdapterStatus.DEGRADED
            notes = (
                f"Partial: GEMI={'ok' if gemi_reachable else 'down'}, "
                f"VIES={'ok' if vies_ok else 'down'}."
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": gemi_reachable, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # GEMI publicity portal exposes a JSON search backing the public UI;
        # the response shape has evolved over time, so we tolerate both an
        # `items`/`companies`/`results` envelope and a top-level list.
        async with build_http_client(base_url=self.GEMI_BASE_URL, timeout=20.0) as client:
            resp = await get_with_retry(
                client,
                "/api/companies",
                params={"searchTerm": name, "page": 1, "pageSize": min(limit, 50)},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                return []

        items = _extract_items(payload)
        out: list[CompanyMatch] = []
        for item in items[:limit]:
            gemi = _str_or_none(
                item.get("gemiNumber")
                or item.get("gemi")
                or item.get("arGEMH")
                or item.get("registryNumber")
            )
            if not gemi:
                continue
            afm = _str_or_none(item.get("afm") or item.get("vatNumber") or item.get("taxId"))
            display_name = (
                item.get("companyName")
                or item.get("name")
                or item.get("title")
                or ""
            )
            ids: list[RegistryIdentifier] = [
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=gemi, label="GEMI"
                )
            ]
            if afm and _AFM_RE.match(afm):
                ids.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT, value=f"EL{afm}", label="ΑΦΜ"
                    )
                )
            out.append(
                CompanyMatch(
                    id=gemi,
                    name=str(display_name).strip(),
                    country=self.country_code,
                    identifiers=ids,
                    address=_first_str(
                        item.get("address"),
                        item.get("registeredAddress"),
                        item.get("headquarters"),
                    ),
                    status=_str_or_none(item.get("status") or item.get("companyStatus")),
                    source_url=f"{self.GEMI_BASE_URL}/company/{gemi}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_gemi(_normalize_gemi(value))
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(_normalize_afm(value))
        raise InvalidIdentifierError(
            f"GR supports COMPANY_NUMBER (GEMI) or VAT (ΑΦΜ), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # ATHEX hosts free annual report PDFs but its index is a JSP grid with
        # no stable JSON surface; integration is deferred. Non-listed firms
        # have no free filings source.
        return []

    async def _lookup_by_gemi(self, gemi: str) -> CompanyDetails | None:
        async with build_http_client(base_url=self.GEMI_BASE_URL, timeout=20.0) as client:
            resp = await get_with_retry(client, f"/api/companies/{gemi}/details")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                return None

        if not isinstance(data, dict) or not data:
            return None

        afm = _str_or_none(data.get("afm") or data.get("vatNumber") or data.get("taxId"))
        identifiers: list[RegistryIdentifier] = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=gemi, label="GEMI"
            )
        ]
        if afm and _AFM_RE.match(afm):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=f"EL{afm}", label="ΑΦΜ"
                )
            )

        capital = _to_float(data.get("capital") or data.get("shareCapital"))

        return CompanyDetails(
            id=gemi,
            name=_first_str(
                data.get("companyName"),
                data.get("name"),
                data.get("title"),
            )
            or gemi,
            country="GR",
            legal_form=_first_str(
                data.get("legalForm"), data.get("companyType"), data.get("type")
            ),
            status=_first_str(data.get("status"), data.get("companyStatus")),
            incorporation_date=_parse_date(
                _first_str(
                    data.get("incorporationDate"),
                    data.get("establishmentDate"),
                    data.get("registrationDate"),
                )
            ),
            dissolution_date=_parse_date(
                _first_str(data.get("dissolutionDate"), data.get("ceaseDate"))
            ),
            registered_address=_first_str(
                data.get("address"),
                data.get("registeredAddress"),
                data.get("headquarters"),
            ),
            capital_amount=capital,
            capital_currency="EUR" if capital is not None else None,
            identifiers=identifiers,
            website=_first_str(data.get("website"), data.get("url")),
            phone=_first_str(data.get("phone"), data.get("telephone")),
            email=_first_str(data.get("email")),
            raw=data,
            source_url=f"{self.GEMI_BASE_URL}/company/{gemi}",
        )

    async def _lookup_by_vat(self, afm: str) -> CompanyDetails | None:
        vies = await self._vies_check(afm)
        if not vies or not vies.get("valid"):
            return None
        return CompanyDetails(
            id=afm,
            name=(vies.get("name") or "").strip() or afm,
            country="GR",
            status="active",
            registered_address=(vies.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=f"EL{afm}", label="ΑΦΜ"
                ),
            ],
            raw={"vies": vies},
            source_url=(
                f"{self.GEMI_BASE_URL}/companies?searchTerm={afm}"
            ),
        )

    async def _vies_check(self, afm: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="EL", vat=afm)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }
        try:
            async with build_http_client(timeout=30.0, headers=headers) as client:
                resp = await client.post(_VIES_URL, content=envelope)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
        except httpx.HTTPError:
            return None
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
    valid_text = (
        resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or ""
    ).strip().lower()
    valid = valid_text == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "companies", "results", "data", "content"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [x for x in candidate if isinstance(x, dict)]
    return []


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _first_str(*values: Any) -> str | None:
    for v in values:
        s = _str_or_none(v)
        if s:
            return s
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
