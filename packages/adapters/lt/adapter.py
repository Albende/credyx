"""Lithuania adapter — Registrų centras (JAR) + VIES.

Free, public Lithuanian data sources usable without a paid license:

- Registrų centras (the Centre of Registers) operates JAR — the Legal
  Entities Register — with a free public name search and per-company
  detail pages at https://www.registrucentras.lt/jar/p/. Structured
  extracts of filed annual reports ("finansinės ataskaitos") are sold
  per document and are out of scope for the MVP per project rules; only
  the list of available filing years is free.
- VIES is the cheapest reliable way to resolve an LT VAT to a name +
  registered address.

Identifier scope:
- COMPANY_NUMBER → Įmonės kodas, 9 digits (e.g. ``121215434``).
- VAT             → ``LT`` + 9 or 12 digits.

Capabilities:
- search_by_name → scrape the public JAR search results page.
- lookup_by_identifier(VAT)            → VIES SOAP.
- lookup_by_identifier(COMPANY_NUMBER) → JAR search keyed by code.
- fetch_financials                     → list filing years (metadata only);
  PDFs are paid extracts on JAR.

If the JAR HTML changes shape or the registry hard-blocks (CAPTCHA / WAF)
callers see the underlying httpx error or an empty result — we never
fabricate registry data.
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

_IMONES_KODAS_RE = re.compile(r"^\d{9}$")
_LT_VAT_RE = re.compile(r"^\d{9}(\d{3})?$")

# Telia Lietuva — a stable, always-valid LT VAT for live health probes.
_VIES_HEALTH_PROBE = "100001969712"

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


def _normalize_imones_kodas(value: str) -> str:
    """Return a canonical 9-digit įmonės kodas."""
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("LT"):
        cleaned = cleaned[2:]
    if not _IMONES_KODAS_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Lithuanian įmonės kodas must be 9 digits: {value}"
        )
    return cleaned


def _normalize_lt_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("LT"):
        cleaned = cleaned[2:]
    if not _LT_VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Lithuanian VAT must be 'LT' + 9 or 12 digits: {value}"
        )
    return cleaned


class LTAdapter(CountryAdapter):
    country_code = "LT"
    country_name = "Lithuania"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    JAR_BASE = "https://www.registrucentras.lt"
    JAR_SEARCH_URL = "https://www.registrucentras.lt/jar/p/index.php"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(
                    client,
                    self.JAR_SEARCH_URL,
                    params={"p": "1", "kodas": "121215434"},
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"JAR probe failed: {str(exc)[:160]}",
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"JAR returned HTTP {resp.status_code}.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via JAR (įmonės kodas) or VIES (VAT). "
                "Annual report PDFs are paid extracts on JAR; only metadata "
                "(filing years) is returned by fetch_financials."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        params = {"p": "1", "pavadinimas": name}
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.JAR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        return _parse_jar_search_results(resp.text, country=self.country_code)[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_kodas(value)
        raise InvalidIdentifierError(
            f"LT supports COMPANY_NUMBER (įmonės kodas) or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        kodas = _normalize_imones_kodas(company_id)
        params = {"p": "1", "Tab": "2", "kodas": kodas}
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.JAR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        filing_years = _parse_jar_filing_years(resp.text)
        cutoff = datetime.utcnow().year - years
        filings: list[FinancialFiling] = []
        for fy in sorted(filing_years, reverse=True):
            if fy < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=kodas,
                    year=fy,
                    type=FilingType.ANNUAL_REPORT,
                    currency="EUR",
                    structured_data=None,
                    document_url=None,  # paid extract — not free-fetchable
                    document_format="pdf",
                    source_url=(
                        f"{self.JAR_SEARCH_URL}?p=1&Tab=2&kodas={kodas}"
                    ),
                )
            )
        return filings

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_lt_vat(value)
        result = await self._vies_check(vat)
        if not result or not result.get("valid"):
            return None
        identifiers = [
            RegistryIdentifier(type=IdentifierType.VAT, value=f"LT{vat}", label="PVM kodas"),
        ]
        return CompanyDetails(
            id=f"LT{vat}",
            name=(result.get("name") or "").strip() or f"LT{vat}",
            country="LT",
            status="active",
            registered_address=(result.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": result},
            source_url=None,
        )

    async def _lookup_by_kodas(self, value: str) -> CompanyDetails | None:
        kodas = _normalize_imones_kodas(value)
        params = {"p": "1", "kodas": kodas}
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.JAR_SEARCH_URL, params=params)
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        matches = _parse_jar_search_results(resp.text, country=self.country_code)
        match = _pick_match_by_kodas(matches, kodas)
        if match is None:
            return None
        return CompanyDetails(
            id=kodas,
            name=match.name,
            country="LT",
            status=match.status,
            registered_address=match.address,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=kodas,
                    label="Įmonės kodas",
                ),
            ],
            raw={"jar_row": match.model_dump()},
            source_url=match.source_url or f"{self.JAR_SEARCH_URL}?p=1&kodas={kodas}",
        )

    async def _vies_check(self, vat: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="LT", vat=vat)
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        async with build_http_client(timeout=30.0, headers=headers) as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)


class _JARResultsParser(HTMLParser):
    """Minimal HTML parser pulling company rows from the JAR results table.

    JAR's results page renders one or more tables; rows for legal entities
    embed the 9-digit įmonės kodas and the denomination. We collect every
    table-row and let the post-processing pass extract the kodas + name.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row_links: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []
        self._row_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = {k: v for k, v in attrs}
        if tag == "tr":
            self._in_row = True
            self._row = []
            self._row_hrefs = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
        elif self._in_row and tag == "a":
            href = attrd.get("href")
            if href:
                self._row_hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            self._row.append("".join(self._cell).strip())
            self._cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
                self.row_links.append(self._row_hrefs)
            self._row = []
            self._row_hrefs = []
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


_KODAS_IN_TEXT = re.compile(r"\b(\d{9})\b")
_STATUS_HINTS = (
    "registruot",
    "išregistruot",
    "isregistruot",
    "likviduojam",
    "bankrut",
    "reorganizuojam",
)


def _parse_jar_search_results(html: str, *, country: str) -> list[CompanyMatch]:
    parser = _JARResultsParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    for row, hrefs in zip(parser.rows, parser.row_links):
        kodas = _extract_kodas_from_row(row)
        if not kodas or kodas in seen:
            continue
        name = _extract_name_from_row(row, kodas)
        if not name:
            continue
        seen.add(kodas)
        status = _extract_status_from_row(row)
        source_url = _pick_detail_href(hrefs) or (
            f"https://www.registrucentras.lt/jar/p/index.php?p=1&kodas={kodas}"
        )
        matches.append(
            CompanyMatch(
                id=kodas,
                name=name,
                country=country,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=kodas,
                        label="Įmonės kodas",
                    )
                ],
                status=status,
                source_url=source_url,
            )
        )
    return matches


def _extract_kodas_from_row(row: list[str]) -> str | None:
    for cell in row:
        m = _KODAS_IN_TEXT.search(cell)
        if m:
            return m.group(1)
    return None


def _extract_name_from_row(row: list[str], kodas: str | None) -> str | None:
    """Pick the row's denomination — the longest non-kodas, non-status cell."""
    best: str | None = None
    for cell in row:
        if not cell:
            continue
        if kodas and kodas in cell and len(cell.strip()) <= 12:
            continue
        low = cell.lower()
        if any(h in low for h in _STATUS_HINTS) and len(cell) < 30:
            continue
        if cell.isdigit():
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


def _pick_detail_href(hrefs: list[str]) -> str | None:
    for href in hrefs:
        if "kodas=" in href or "jar/p" in href:
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                return f"https://www.registrucentras.lt{href}"
            return f"https://www.registrucentras.lt/jar/p/{href}"
    return None


def _pick_match_by_kodas(matches: list[CompanyMatch], kodas: str) -> CompanyMatch | None:
    for m in matches:
        if m.id == kodas:
            return m
    return matches[0] if len(matches) == 1 else None


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
# JAR's "Finansinės ataskaitos" tab marks filing rows with terms like
# "metinė", "metinis", "ataskaita", "FA"; we pull every 4-digit year that
# co-occurs with one of these tokens to avoid scraping unrelated years
# (incorporation dates etc.).
_FINANCIAL_HINTS = (
    "metin",
    "ataskait",
    "finans",
    "balans",
    "fa20",
    "fa 20",
)


def _parse_jar_filing_years(html: str) -> set[int]:
    parser = _JARResultsParser()
    try:
        parser.feed(html)
    except Exception:
        return set()
    years: set[int] = set()
    current = datetime.utcnow().year
    for row in parser.rows:
        joined = " ".join(row).lower()
        if not any(h in joined for h in _FINANCIAL_HINTS):
            continue
        for cell in row:
            for m in _YEAR_RE.finditer(cell):
                y = int(m.group(1))
                if 1990 <= y <= current:
                    years.add(y)
    return years


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
