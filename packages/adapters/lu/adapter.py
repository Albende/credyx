"""Luxembourg adapter — LBR (Registre de Commerce et des Sociétés) + VIES.

Luxembourg has two free, authoritative public sources usable without paid
licensing:

- LBR / RCSL (https://www.lbr.lu/) exposes a free public name search and
  per-company HTML detail pages keyed by an "RCS" identifier ("B" + 5–6
  digits). Full filed extracts (statuts, comptes annuels) are paywalled
  per document and out of scope for the MVP per project rules.
- VIES confirms an LU VAT registration and returns the registered name +
  address; the cheapest reliable way to resolve an LU VAT to a company.

Identifier scope:
- COMPANY_NUMBER → RCS B-number ("B82454", "82454", "B 82 454" all valid).
- VAT             → LU + 8 digits.

Capabilities:
- search_by_name → scrape the public LBR search results page.
- lookup_by_identifier(VAT)            → VIES SOAP.
- lookup_by_identifier(COMPANY_NUMBER) → LBR detail page scrape.
- fetch_financials                     → []; filings are paid extracts on LBR.

If LBR's HTML changes shape (it has historically) or returns a CAPTCHA /
hard-block, callers see the underlying httpx error or an empty result —
we never fabricate registry data.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_RCS_RE = re.compile(r"^B?\d{1,7}$")
_LU_VAT_RE = re.compile(r"^\d{8}$")

_VIES_HEALTH_PROBE = "24876214"  # ArcelorMittal — stable, always-valid LU VAT

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


def _normalize_rcs(value: str) -> str:
    """Return a canonical RCS number like "B82454"."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "")
    if cleaned.startswith("RCS"):
        cleaned = cleaned[3:]
    if cleaned.startswith("B"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit() or not (1 <= len(cleaned) <= 7):
        raise InvalidIdentifierError(
            f"Luxembourg RCS number must be 'B' + digits: {value}"
        )
    return f"B{cleaned}"


def _normalize_lu_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("LU"):
        cleaned = cleaned[2:]
    if not _LU_VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Luxembourg VAT must be 'LU' + 8 digits: {value}"
        )
    return cleaned


class LUAdapter(CountryAdapter):
    country_code = "LU"
    country_name = "Luxembourg"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    LBR_BASE = "https://www.lbr.lu"
    LBR_SEARCH_URL = (
        "https://www.lbr.lu/mjrcs/jsp/IndexActionNotSecured.action"
    )
    LBR_DETAIL_URL = (
        "https://www.lbr.lu/mjrcs/jsp/DisplayConsultDocDetailsActionNotSecured.action"
    )

    async def health_check(self) -> AdapterHealth:
        try:
            payload = await self._vies_check(_VIES_HEALTH_PROBE)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if not payload or not payload.get("valid"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="VIES reachable but ArcelorMittal VAT reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via VIES (VAT) or LBR HTML (RCS). "
                "Financial extracts are paid documents on LBR and not returned."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        params = {
            "FROM_MENU": "true",
            "time": "0",
            "currentMenuLabel": "MENU_CONSULT_RCS",
            "currentMenuPath": "MENU_CONSULT_RCS",
            "queryType1": "EXACT",
            "denomination": name,
        }
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.LBR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        return _parse_lbr_search_results(resp.text, country=self.country_code)[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_rcs(value)
        raise InvalidIdentifierError(
            f"LU supports COMPANY_NUMBER (RCS) or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # LBR sells filed accounts ("comptes annuels") per document; no free
        # structured feed exists. Returning an empty list keeps the contract
        # honest — see docs/countries/lu.md for the paid-source upgrade path.
        return []

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_lu_vat(value)
        result = await self._vies_check(vat)
        if not result or not result.get("valid"):
            return None
        identifiers = [
            RegistryIdentifier(type=IdentifierType.VAT, value=f"LU{vat}", label="VAT"),
        ]
        return CompanyDetails(
            id=f"LU{vat}",
            name=(result.get("name") or "").strip() or f"LU{vat}",
            country="LU",
            status="active",
            registered_address=(result.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": result},
            source_url=None,
        )

    async def _lookup_by_rcs(self, value: str) -> CompanyDetails | None:
        rcs = _normalize_rcs(value)
        # First try the search endpoint with the RCS itself — LBR accepts it
        # as a free-text query and returns the canonical row. This avoids
        # depending on internal action IDs whose schema is undocumented.
        params = {
            "FROM_MENU": "true",
            "time": "0",
            "currentMenuLabel": "MENU_CONSULT_RCS",
            "currentMenuPath": "MENU_CONSULT_RCS",
            "queryType1": "EXACT",
            "rcsNumber": rcs,
        }
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.LBR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        matches = _parse_lbr_search_results(resp.text, country=self.country_code)
        match = _pick_match_by_rcs(matches, rcs)
        if match is None:
            return None
        return CompanyDetails(
            id=rcs,
            name=match.name,
            country="LU",
            status=match.status,
            registered_address=match.address,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=rcs, label="RCS"
                ),
            ],
            raw={"lbr_row": match.model_dump()},
            source_url=match.source_url or self.LBR_SEARCH_URL,
        )

    async def _vies_check(self, vat: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="LU", vat=vat)
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


class _LBRResultsParser(HTMLParser):
    """Minimal HTML parser pulling rows from the LBR search results table.

    LBR's results page renders a single results table; each company row
    contains the RCS number, the denomination, the legal form, and a status.
    The exact column order is stable in the public template at time of
    writing — defensive lookups handle minor reorderings.
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
            if "result" in css or "consult" in css or self._in_table is False:
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


_RCS_IN_TEXT = re.compile(r"\bB\s?\d{1,7}\b", re.IGNORECASE)
_STATUS_HINTS = ("active", "radié", "radie", "dissoute", "liquidation", "inactive")


def _parse_lbr_search_results(html: str, *, country: str) -> list[CompanyMatch]:
    parser = _LBRResultsParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    for row in parser.rows:
        rcs = _extract_rcs_from_row(row)
        name = _extract_name_from_row(row, rcs)
        if not rcs or not name:
            continue
        if rcs in seen:
            continue
        seen.add(rcs)
        status = _extract_status_from_row(row)
        matches.append(
            CompanyMatch(
                id=rcs,
                name=name,
                country=country,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER, value=rcs, label="RCS"
                    )
                ],
                status=status,
                source_url=f"https://www.lbr.lu/mjrcs/jsp/IndexActionNotSecured.action?rcsNumber={rcs}",
            )
        )
    return matches


def _extract_rcs_from_row(row: list[str]) -> str | None:
    for cell in row:
        m = _RCS_IN_TEXT.search(cell)
        if m:
            digits = re.sub(r"\D", "", m.group(0))
            if digits:
                return f"B{digits}"
    return None


def _extract_name_from_row(row: list[str], rcs: str | None) -> str | None:
    """Pick the row's denomination — the longest non-RCS, non-status cell."""
    best: str | None = None
    for cell in row:
        if not cell:
            continue
        if rcs and rcs[1:] in cell.replace(" ", ""):
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


def _pick_match_by_rcs(matches: list[CompanyMatch], rcs: str) -> CompanyMatch | None:
    for m in matches:
        if m.id.upper() == rcs.upper():
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
