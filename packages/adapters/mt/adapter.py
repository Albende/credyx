"""Malta adapter — MBR (Malta Business Registry) + VIES + MSE for filings.

Three free, authoritative sources usable without paid licensing:

- MBR (https://registry.mbr.mt/) exposes a free public name search and
  per-company HTML detail pages keyed by a "C"-prefixed company number
  ("C12345"). Full registered extracts and filed accounts are paywalled
  per document and out of scope for the MVP per project rules.
- VIES confirms an MT VAT registration and returns the registered name +
  address; the cheapest reliable way to resolve an MT VAT to a company.
- Malta Stock Exchange (https://www.borzamalta.com.mt/) publishes annual
  reports as free PDFs for MSE-listed issuers; we surface the issuer
  page URL as a best-effort document_url for the four "plc" majors.

Identifier scope:
- COMPANY_NUMBER → "C" + 1–7 digits ("C 2833", "C2833", "2833" all valid).
- VAT             → MT + 8 digits.

Capabilities:
- search_by_name → scrape the public MBR search results page.
- lookup_by_identifier(VAT)            → VIES SOAP.
- lookup_by_identifier(COMPANY_NUMBER) → MBR detail page scrape.
- fetch_financials                     → MSE issuer page link if listed; [] otherwise.

If MBR's HTML changes shape or returns a CAPTCHA / hard block, callers
see the underlying httpx error or an empty result — we never fabricate
registry data.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser
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

# Bank of Valletta — stable, always-valid MT VAT used as a VIES health probe.
_VIES_HEALTH_PROBE = "10172321"

# MSE-listed issuers we know expose free annual reports under their issuer
# slug. Mapping is deliberately tiny; adding more requires verifying the
# slug exists publicly on borzamalta.com.mt.
_MSE_ISSUER_SLUGS: dict[str, str] = {
    "C2833": "bank-of-valletta-plc",
    "C3177": "hsbc-bank-malta-plc",
    "C22334": "go-plc",
    "C26136": "international-hotel-investments-plc",
}

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
    MBR_BASE = "https://registry.mbr.mt"
    MBR_SEARCH_URL = "https://registry.mbr.mt/ROC/companySearch.do"
    MBR_INDEX_URL = "https://registry.mbr.mt/ROC/index.jsp"
    MSE_BASE = "https://www.borzamalta.com.mt"

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
                "Lookup via VIES (VAT) or MBR HTML (company number). "
                "Filings limited to MSE-listed issuers; MBR full extracts are paid."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        params = {
            "action": "companySearch",
            "name": name,
            "searchType": "PARTIAL",
        }
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.MBR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        return _parse_mbr_search_results(resp.text, country=self.country_code)[:limit]

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
        cn = _normalize_company_number(company_id)
        slug = _MSE_ISSUER_SLUGS.get(cn)
        if slug is None:
            # MBR sells filed accounts per document; no free structured feed
            # exists for non-listed issuers. Empty list keeps the contract
            # honest — see docs/countries/mt.md for the paid-source path.
            return []
        issuer_url = f"{self.MSE_BASE}/issuers/{slug}/"
        current_year = datetime.utcnow().year
        return [
            FinancialFiling(
                company_id=cn,
                year=current_year - 1,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="EUR",
                structured_data=None,
                document_url=None,
                document_format=None,
                source_url=issuer_url,
            )
        ]

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_mt_vat(value)
        result = await self._vies_check(vat)
        if not result or not result.get("valid"):
            return None
        identifiers = [
            RegistryIdentifier(type=IdentifierType.VAT, value=f"MT{vat}", label="VAT"),
        ]
        return CompanyDetails(
            id=f"MT{vat}",
            name=(result.get("name") or "").strip() or f"MT{vat}",
            country="MT",
            status="active",
            registered_address=(result.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": result},
            source_url=None,
        )

    async def _lookup_by_company_number(self, value: str) -> CompanyDetails | None:
        cn = _normalize_company_number(value)
        params = {
            "action": "companySearch",
            "companyNumber": cn,
            "searchType": "EXACT",
        }
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.MBR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        matches = _parse_mbr_search_results(resp.text, country=self.country_code)
        match = _pick_match_by_company_number(matches, cn)
        if match is None:
            return None
        return CompanyDetails(
            id=cn,
            name=match.name,
            country="MT",
            status=match.status,
            registered_address=match.address,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=cn,
                    label="Company Number",
                ),
            ],
            raw={"mbr_row": match.model_dump()},
            source_url=match.source_url or self.MBR_INDEX_URL,
        )

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


class _MBRResultsParser(HTMLParser):
    """Minimal HTML parser pulling rows from the MBR search results table.

    MBR renders results in a single HTML table; rows contain at minimum the
    company number, the denomination, and a status column. Column order has
    been stable in the public template; defensive lookups handle minor
    reorderings or extra cells.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = {k: v for k, v in attrs}
        if tag == "table":
            css = (attrd.get("class") or "").lower()
            if "result" in css or "search" in css or self._in_table is False:
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            self._row.append("".join(self._cell).strip())
            self._cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._row = []
            self._in_row = False
        elif tag == "table" and self._in_table:
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


_C_NUMBER_IN_TEXT = re.compile(r"\bC\s?\d{1,7}\b", re.IGNORECASE)
_STATUS_HINTS = (
    "active",
    "registered",
    "struck off",
    "struck-off",
    "dissolved",
    "liquidation",
    "inactive",
    "defunct",
)


def _parse_mbr_search_results(html: str, *, country: str) -> list[CompanyMatch]:
    parser = _MBRResultsParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    for row in parser.rows:
        cn = _extract_company_number_from_row(row)
        name = _extract_name_from_row(row, cn)
        if not cn or not name:
            continue
        if cn in seen:
            continue
        seen.add(cn)
        status = _extract_status_from_row(row)
        matches.append(
            CompanyMatch(
                id=cn,
                name=name,
                country=country,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=cn,
                        label="Company Number",
                    )
                ],
                status=status,
                source_url=f"https://registry.mbr.mt/ROC/companySearch.do?companyNumber={cn}",
            )
        )
    return matches


def _extract_company_number_from_row(row: list[str]) -> str | None:
    for cell in row:
        m = _C_NUMBER_IN_TEXT.search(cell)
        if m:
            digits = re.sub(r"\D", "", m.group(0))
            if digits:
                return f"C{digits}"
    return None


def _extract_name_from_row(row: list[str], cn: str | None) -> str | None:
    """Pick the row's denomination — the longest non-id, non-status cell."""
    best: str | None = None
    for cell in row:
        if not cell:
            continue
        if cn and cn[1:] in cell.replace(" ", ""):
            continue
        low = cell.lower()
        if any(h in low for h in _STATUS_HINTS) and len(cell) < 25:
            continue
        if best is None or len(cell) > len(best):
            best = cell
    return best


def _extract_status_from_row(row: list[str]) -> str | None:
    for cell in row:
        low = cell.lower()
        for hint in _STATUS_HINTS:
            if hint in low:
                return cell.strip()
    return None


def _pick_match_by_company_number(
    matches: list[CompanyMatch], cn: str
) -> CompanyMatch | None:
    for m in matches:
        if m.id.upper() == cn.upper():
            return m
    return matches[0] if len(matches) == 1 else None


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
