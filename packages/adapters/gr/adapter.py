"""Greece adapter — GEMI publicity portal + VIES VAT.

Two complementary free sources:

- GEMI (Geniko Emporiko Mitroo, General Commercial Registry) is the
  official corporate registry. Its public-disclosure portal at
  https://publicity.businessportal.gr/ serves a JSON-backed search and
  detail surface (verified 2026-07-20):
  - ``POST /api/searchCompany`` with the full ``dataToBeSent`` envelope the
    Next.js UI sends (``inputField`` carries the query; omitting the other
    keys returns a 500) → ``{"total": ..., "hits": [...]}``.
  - ``POST /api/company/details`` with ``{"query": {"arGEMI": gemi},
    "token": null, "language": "en"}`` → ``{"companyInfo": {"payload":
    {"company": {...}, "capital": [...], ...}}}``; 404 for unknown GEMI.
  The backend accepts ``token: null`` (the browser UI sends a reCAPTCHA
  token, but it is not enforced server-side today).
- VIES (EU VAT Information Exchange) covers ΑΦΜ lookups under the EL
  country prefix and returns the registered legal name + address.

Financials come from the same GEMI ``company/details`` payload: its
``companyFinancial`` array lists every filed annual financial statement
(``referencePeriod`` + a ``balancesheet`` entry with a numeric ``id``).
Each file downloads as a PDF from
``GET /api/download/financial/{id}?companyId={gemi}`` (verified live
2026-07-21 for OTE, Coca-Cola 3E and OPAP; ESEF-listed firms also expose
an ``ixbrl_url``). No API key, no CAPTCHA.

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
from packages.adapters._base.errors import InvalidIdentifierError, RateLimitError
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
                "GEMI publicity portal + VIES reachable. Annual financial "
                "statements served as PDF from the GEMI filings endpoint."
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
            capabilities={"search": gemi_reachable, "lookup": True, "financials": gemi_reachable},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.GEMI_BASE_URL, timeout=20.0) as client:
            resp = await client.post(
                "/api/searchCompany",
                json={
                    "dataToBeSent": _search_data(name, page=1),
                    "token": None,
                    "language": "en",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return []
            if resp.status_code == 429:
                raise RateLimitError(
                    "GEMI publicity portal rate-limited the search (429) — "
                    "back off before retrying."
                )
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
                or item.get("id")
                or item.get("gemi")
                or item.get("arGEMI")
            )
            if not gemi:
                continue
            afm = _str_or_none(item.get("afm") or item.get("vatNumber") or item.get("taxId"))
            display_name = _first_str(
                item.get("name"),
                item.get("companyName"),
                _first_of_list(item.get("title")),
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
                    name=display_name or gemi,
                    country=self.country_code,
                    identifiers=ids,
                    address=_str_or_none(item.get("addressCity")),
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
        gemi = _normalize_gemi(company_id)
        async with build_http_client(base_url=self.GEMI_BASE_URL, timeout=30.0) as client:
            resp = await client.post(
                "/api/company/details",
                json={"query": {"arGEMI": gemi}, "token": None, "language": "en"},
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return []
            if resp.status_code == 429:
                raise RateLimitError(
                    "GEMI publicity portal rate-limited the financials fetch "
                    "(429) — back off before retrying."
                )
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                return []

        payload = ((data or {}).get("companyInfo") or {}).get("payload") or {}
        entries = payload.get("companyFinancial") or []

        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for entry in entries:
            period_end = _period_end(_str_or_none(entry.get("referencePeriod")))
            if period_end is None or period_end.year in seen_years:
                continue
            groups = entry.get("FilesAndAuditors") or []
            first = groups[0] if groups else {}
            for sheet in first.get("balancesheet") or []:
                file_id = sheet.get("id")
                if file_id is None:
                    continue
                seen_years.add(period_end.year)
                filings.append(
                    FinancialFiling(
                        company_id=gemi,
                        year=period_end.year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=period_end,
                        currency="EUR",
                        document_url=(
                            f"{self.GEMI_BASE_URL}/api/download/financial/"
                            f"{int(file_id)}?companyId={gemi}"
                        ),
                        document_format="pdf",
                        source_url=f"{self.GEMI_BASE_URL}/company/{gemi}",
                    )
                )
                break

        filings.sort(key=lambda f: f.year, reverse=True)
        return filings[:years]

    async def _lookup_by_gemi(self, gemi: str) -> CompanyDetails | None:
        async with build_http_client(base_url=self.GEMI_BASE_URL, timeout=20.0) as client:
            resp = await client.post(
                "/api/company/details",
                json={"query": {"arGEMI": gemi}, "token": None, "language": "en"},
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                raise RateLimitError(
                    "GEMI publicity portal rate-limited the lookup (429) — "
                    "back off before retrying."
                )
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                return None

        payload = ((data or {}).get("companyInfo") or {}).get("payload") or {}
        company = payload.get("company") or {}
        if not company:
            return None

        afm = _str_or_none(company.get("afm"))
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

        capital_entries = payload.get("capital") or []
        first_capital = capital_entries[0] if capital_entries else {}
        capital = _to_float(first_capital.get("amount"))

        legal_type = company.get("legalType")
        status_obj = company.get("companyStatus")

        return CompanyDetails(
            id=gemi,
            name=_first_str(company.get("name"), company.get("namei18n")) or gemi,
            country="GR",
            legal_form=(
                _str_or_none(legal_type.get("desc"))
                if isinstance(legal_type, dict)
                else _str_or_none(legal_type)
            ),
            status=(
                _str_or_none(status_obj.get("status"))
                if isinstance(status_obj, dict)
                else _str_or_none(status_obj)
            ),
            incorporation_date=_parse_date(
                _first_str(
                    company.get("dateStart"), company.get("dateGemiRegistered")
                )
            ),
            registered_address=_first_str(
                company.get("company_address"), company.get("company_address_map")
            ),
            capital_amount=capital,
            capital_currency=(
                _str_or_none(first_capital.get("currency")) or "EUR"
                if capital is not None
                else None
            ),
            identifiers=identifiers,
            website=_str_or_none(company.get("companyWebsite")),
            raw={"company": company, "capital": capital_entries},
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


def _search_data(input_field: str, page: int) -> dict[str, Any]:
    """Full ``dataToBeSent`` envelope; the backend 500s if keys are missing."""
    return {
        "inputField": input_field,
        "city": None,
        "postcode": None,
        "legalType": [],
        "status": [],
        "suspension": [],
        "category": [],
        "specialCharacteristics": [],
        "employeeNumber": [],
        "armodiaGEMI": [],
        "kad": [],
        "recommendationDateFrom": None,
        "recommendationDateTo": None,
        "closingDateFrom": None,
        "closingDateTo": None,
        "alterationDateFrom": None,
        "alterationDateTo": None,
        "person": [],
        "personrecommendationDateFrom": None,
        "personrecommendationDateTo": None,
        "radioValue": "all",
        "places": [],
        "page": page,
    }


def _first_of_list(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return _str_or_none(value[0])
    return None


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("hits", "items", "companies", "results", "data", "content"):
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


def _period_end(reference_period: str | None) -> date | None:
    """``"01/01/2025 - 31/12/2025"`` → the closing date of the period."""
    if not reference_period:
        return None
    parts = reference_period.split("-")
    if len(parts) != 2:
        return None
    return _parse_date(parts[1].strip())


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    text = s[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    # GEMI serves dates as DD/MM/YYYY.
    try:
        d, m, y = text.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, IndexError):
        return None
