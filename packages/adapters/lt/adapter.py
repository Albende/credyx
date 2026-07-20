"""Lithuania adapter — Registrų centras (JAR) open data + JAR portal + VIES.

Free, public Lithuanian data sources usable without a paid license or key:

- **JAR open data (Spinta API on data.gov.lt)** — Registrų centras publishes
  the full Legal Entities Register as machine-readable open data served by the
  Spinta layer at ``https://get.data.gov.lt/datasets/gov/rc/jar/``. The
  ``iregistruoti/JuridinisAsmuo`` dataset is queried by exact ``ja_kodas`` for a
  fast, key-free company lookup (name, legal form, status, registration dates).
  Text search (``ja_pavadinimas``) and the financial-statement datasets are not
  indexed on the API, so filtering them per company times out — the JAR portal
  is used for those instead.
- **JAR public portal** (``https://www.registrucentras.lt/jar/p/``) — the free
  name search and per-company document list. The portal sits behind Cloudflare,
  so requests go through ``fetch_with_bot_bypass`` (FlareSolverr). The document
  list (``dok.php?kod=``) enumerates the filed annual financial-statement sets
  ("Finansinės atskaitomybės dokumentai / YYYY m. …") — real per-company filing
  metadata. The PDFs themselves are paid extracts, so no ``document_url`` is
  emitted; only the filing years are surfaced.
- **VIES** resolves an LT VAT to a registered name + address.

Identifier scope:
- COMPANY_NUMBER → Įmonės kodas, 9 digits (e.g. ``121215434``).
- VAT             → ``LT`` + 9 or 12 digits.

Capabilities:
- search_by_name                       → JAR portal name search (FlareSolverr).
- lookup_by_identifier(COMPANY_NUMBER) → JAR open-data Spinta query.
- lookup_by_identifier(VAT)            → VIES SOAP.
- fetch_financials                     → JAR portal document list (filing years,
  metadata only); the filed PDFs are paid extracts on JAR.

We never fabricate registry data — if a source is down or returns nothing the
caller sees an empty result, not invented numbers.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, fetch_with_bot_bypass
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

_SPINTA_BASE = "https://get.data.gov.lt/datasets/gov/rc/jar"
_JAR_PORTAL = "https://www.registrucentras.lt/jar/p"

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


def _fix_lt_encoding(value: str | None) -> str | None:
    """Undo the double UTF-8 encoding in JAR open-data text fields.

    Spinta serves Lithuanian diacritics as UTF-8 bytes re-interpreted as
    Latin-1 (``ų`` arrives as ``Å³``). Round-tripping recovers the original;
    strings that already hold real Unicode (code points above U+00FF) can't be
    Latin-1 encoded, so they're returned untouched.
    """
    if not value:
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def _spinta_get(url: str, *, attempts: int = 4, timeout: float = 25.0) -> list[dict]:
    """GET a Spinta endpoint, returning ``_data``.

    The public data.gov.lt server intermittently drops connections or returns
    an empty body under load; retry a few times before giving up.
    """
    headers = {"Accept": "application/json"}
    async with build_http_client(timeout=timeout, headers=headers) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.get(url)
            except (httpx.TransportError, httpx.TimeoutException):
                await asyncio.sleep(0.5 * attempt)
                continue
            if resp.status_code == 200 and resp.text.strip():
                try:
                    return resp.json().get("_data", [])
                except ValueError:
                    pass
            await asyncio.sleep(0.5 * attempt)
    return []


_CLASSIFIER_CACHE: dict[str, dict[str, dict]] = {}
_CLASSIFIER_LOCK = asyncio.Lock()


async def _load_classifier(name: str) -> dict[str, dict]:
    """Fetch and cache a JAR ``formos_statusai`` classifier ("Forma"/"Statusas")."""
    cached = _CLASSIFIER_CACHE.get(name)
    if cached is not None:
        return cached
    async with _CLASSIFIER_LOCK:
        cached = _CLASSIFIER_CACHE.get(name)
        if cached is not None:
            return cached
        rows = await _spinta_get(f"{_SPINTA_BASE}/formos_statusai/{name}?limit(1000)")
        table = {r["_id"]: r for r in rows if r.get("_id")}
        if table:
            _CLASSIFIER_CACHE[name] = table
        return table


async def _resolve_forma(forma_id: str | None) -> str | None:
    if not forma_id:
        return None
    rec = (await _load_classifier("Forma")).get(forma_id)
    return _fix_lt_encoding(rec.get("pavadinimas")) if rec else None


async def _resolve_status(status_id: str | None, isreg_data: str | None) -> str | None:
    if isreg_data:
        return "deregistered"
    if not status_id:
        return "active"
    rec = (await _load_classifier("Statusas")).get(status_id)
    if rec is None:
        return "active"
    if rec.get("kodas") == 0:
        return "active"
    return _fix_lt_encoding(rec.get("pavadinimas")) or "active"


class LTAdapter(CountryAdapter):
    country_code = "LT"
    country_name = "Lithuania"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    SPINTA_ENTITIES = f"{_SPINTA_BASE}/iregistruoti/JuridinisAsmuo"
    JAR_SEARCH_URL = f"{_JAR_PORTAL}/index.php"
    JAR_DOK_URL = f"{_JAR_PORTAL}/dok.php"

    async def health_check(self) -> AdapterHealth:
        try:
            rows = await _spinta_get(
                f"{self.SPINTA_ENTITIES}?ja_kodas=121215434", attempts=2
            )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"JAR open-data probe failed: {str(exc)[:160]}",
            )
        if not rows:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="JAR open-data endpoint returned no rows for the probe code.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via JAR open data (įmonės kodas) or VIES (VAT); name "
                "search and filing lists via the JAR portal (FlareSolverr). "
                "Annual report PDFs are paid extracts on JAR — fetch_financials "
                "returns filing years only."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        url = f"{self.JAR_SEARCH_URL}?pav={_html.escape(name)}&p=1"
        try:
            html, status, _ = await fetch_with_bot_bypass(url, timeout=30.0)
        except httpx.HTTPError:
            return []
        if status != 200:
            return []
        return _parse_jar_search_results(html, country=self.country_code)[:limit]

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
        url = f"{self.JAR_DOK_URL}?kod={kodas}"
        try:
            html, status, _ = await fetch_with_bot_bypass(url, timeout=30.0)
        except httpx.HTTPError:
            return []
        if status != 200:
            return []
        cutoff = datetime.utcnow().year - years
        filings: list[FinancialFiling] = []
        for fy in _parse_jar_financial_years(html):
            if fy < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=kodas,
                    year=fy,
                    type=FilingType.ANNUAL_REPORT,
                    currency="EUR",
                    structured_data=None,
                    document_url=None,  # filed PDFs are paid extracts on JAR
                    document_format="pdf",
                    source_url=url,
                )
            )
        return filings

    async def _lookup_by_kodas(self, value: str) -> CompanyDetails | None:
        kodas = _normalize_imones_kodas(value)
        rows = await _spinta_get(f"{self.SPINTA_ENTITIES}?ja_kodas={kodas}")
        if not rows:
            return await self._lookup_by_kodas_via_portal(kodas)
        rec = rows[0]
        name = _fix_lt_encoding(rec.get("ja_pavadinimas")) or kodas
        isreg = rec.get("isreg_data")
        forma_id = (rec.get("forma") or {}).get("_id")
        status_id = (rec.get("statusas") or {}).get("_id")
        address = _fix_lt_encoding(rec.get("pilnas_adresas") or rec.get("adresas"))
        return CompanyDetails(
            id=kodas,
            name=name,
            country="LT",
            legal_form=await _resolve_forma(forma_id),
            status=await _resolve_status(status_id, isreg),
            incorporation_date=_parse_iso_date(rec.get("reg_data")),
            dissolution_date=_parse_iso_date(isreg),
            registered_address=address or None,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=kodas,
                    label="Įmonės kodas",
                ),
            ],
            raw={"spinta": rec},
            source_url=f"{self.JAR_SEARCH_URL}?kod={kodas}&p=1",
        )

    async def _lookup_by_kodas_via_portal(self, kodas: str) -> CompanyDetails | None:
        """Fallback for when the JAR open-data server is temporarily down."""
        url = f"{self.JAR_SEARCH_URL}?kod={kodas}&p=1"
        try:
            html, status, _ = await fetch_with_bot_bypass(url, timeout=30.0)
        except httpx.HTTPError:
            return None
        if status != 200:
            return None
        detail = _parse_jar_company_detail(html, kodas)
        if detail is None:
            return None
        return CompanyDetails(
            id=kodas,
            name=detail["name"],
            country="LT",
            legal_form=detail.get("legal_form"),
            status=detail.get("status"),
            registered_address=detail.get("address"),
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=kodas,
                    label="Įmonės kodas",
                ),
            ],
            raw={"jar_portal": detail},
            source_url=url,
        )

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

    async def _vies_check(self, vat: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="LT", vat=vat)
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        async with build_http_client(timeout=30.0, headers=headers) as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


_STATUS_RULES = (
    ("išregistruot", "deregistered"),
    ("isregistruot", "deregistered"),
    ("bankrut", "bankrupt"),
    ("likvid", "liquidation"),
    ("reorganiz", "reorganization"),
    ("neįregistruot", "active"),
    ("neiregistruot", "active"),
)


def _normalize_status_text(text: str) -> str | None:
    low = text.lower()
    if not low:
        return None
    for token, label in _STATUS_RULES:
        if token in low:
            return label
    return text.strip() or None


_ROW_SPLIT_RE = re.compile(r"<tr[\s>]", re.IGNORECASE)
_KODAS_CELL_RE = re.compile(r'data-label="KODAS"[^>]*>\s*(\d{9})')
_NAME_CELL_RE = re.compile(
    r'data-label="PAVADINIMAS[^"]*"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL
)
_FORMA_CELL_RE = re.compile(
    r'data-label="TEISIN[^"]*"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL
)
_BOLD_RE = re.compile(r"<b>(.*?)</b>", re.IGNORECASE | re.DOTALL)


def _parse_jar_search_results(html: str, *, country: str) -> list[CompanyMatch]:
    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    for block in _ROW_SPLIT_RE.split(html):
        km = _KODAS_CELL_RE.search(block)
        if not km:
            continue
        kodas = km.group(1)
        if kodas in seen:
            continue
        nm = _NAME_CELL_RE.search(block)
        if not nm:
            continue
        cell = nm.group(1)
        bold = _BOLD_RE.search(cell)
        name = _clean(bold.group(1)) if bold else _clean(cell.split("<br", 1)[0])
        if not name:
            continue
        address = None
        after = cell.split("</b>", 1)[1] if "</b>" in cell else ""
        after = re.split(r"<a\b", after, 1, flags=re.IGNORECASE)[0]
        address = _clean(after) or None
        status = None
        fm = _FORMA_CELL_RE.search(block)
        if fm:
            parts = re.split(r"<br\s*/?>", fm.group(1), flags=re.IGNORECASE)
            status = _normalize_status_text(_clean(parts[-1])) if parts else None
        seen.add(kodas)
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
                address=address,
                status=status,
                source_url=f"https://www.registrucentras.lt/jar/p/index.php?kod={kodas}&p=1",
            )
        )
    return matches


def _parse_jar_company_detail(html: str, kodas: str) -> dict[str, str | None] | None:
    """Pull one company's name/address/form/status from a JAR result page."""
    for block in _ROW_SPLIT_RE.split(html):
        km = _KODAS_CELL_RE.search(block)
        if not km or km.group(1) != kodas:
            continue
        nm = _NAME_CELL_RE.search(block)
        if not nm:
            continue
        cell = nm.group(1)
        bold = _BOLD_RE.search(cell)
        name = _clean(bold.group(1)) if bold else _clean(cell.split("<br", 1)[0])
        if not name:
            continue
        after = cell.split("</b>", 1)[1] if "</b>" in cell else ""
        after = re.split(r"<a\b", after, 1, flags=re.IGNORECASE)[0]
        legal_form = status = None
        fm = _FORMA_CELL_RE.search(block)
        if fm:
            parts = [
                _clean(p) for p in re.split(r"<br\s*/?>", fm.group(1), flags=re.IGNORECASE)
            ]
            parts = [p for p in parts if p]
            if parts:
                legal_form = parts[0] or None
                status = _normalize_status_text(parts[-1])
        return {
            "name": name,
            "address": _clean(after) or None,
            "legal_form": legal_form,
            "status": status,
        }
    return None


_FA_ROW_RE = re.compile(
    r"finansin[^<]{0,40}dokumentai[^<]*?(\d{4})\s*m\.", re.IGNORECASE
)


def _parse_jar_financial_years(html: str) -> list[int]:
    """Filing years from the JAR document list ("… dokumentai / YYYY m. …")."""
    current = datetime.utcnow().year
    years = {
        int(m.group(1))
        for m in _FA_ROW_RE.finditer(html)
        if 1990 <= int(m.group(1)) <= current
    }
    return sorted(years, reverse=True)


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
