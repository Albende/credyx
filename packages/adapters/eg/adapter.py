"""Egypt adapter — GLEIF registry + AnnualReports.com filings.

Egypt has no free official JSON API: the commercial register (GAFI) and the
Egyptian Tax Authority sit behind sessioned web forms, and the Egyptian
Exchange (egx.com.eg) is walled by F5/Shape bot defence that FlareSolverr
cannot clear. Two key-less sources remain and are used here:

* **GLEIF** stores each Egyptian legal entity's Commercial Registration
  number in ``entity.registeredAs`` (registration authority ``RA888888`` —
  the Ministry of Trade and Industry Commercial Registry). That gives a real
  structured record keyed on the CR number, plus a fulltext name search that
  also matches Arabic legal names through their transliterations.
* **AnnualReports.com** hosts the actual filed annual-report PDFs of listed
  Egyptian issuers (e.g. Commercial International Bank). ``fetch_financials``
  resolves the company name via GLEIF, finds its AnnualReports page, and
  returns only PDFs that genuinely download.

Identifiers:
- ``COMPANY_NUMBER`` — Commercial Registration number (variable digits). An
  LEI (20 alphanumerics) is also accepted and looked up directly.
- ``VAT``            — ETA Tax ID (9 digits, often shown ``NNN-NNN-NNN``).
  Not indexed by any free source, so ``lookup_by_identifier`` for VAT raises.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.adapters._global.gleif import GLEIFClient
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

_GLEIF_BASE = "https://api.gleif.org/api/v1"
_GLEIF_HEADERS = {"Accept": "application/vnd.api+json"}

_AR_BASE = "https://www.annualreports.com"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_CR_RE = re.compile(r"^\d{1,15}$")
_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")
_TAX_ID_RE = re.compile(r"^\d{9}$")
_ACRONYM_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9 &.\-]{1,20})\)")
_AR_RESULT_RE = re.compile(
    r'/Company/([a-z0-9-]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
_AR_PDF_RE = re.compile(
    r'href="(/HostedData/AnnualReportArchive/[^"]+?_(\d{4})\.pdf)"',
    re.IGNORECASE,
)


def _normalize_tax_id(value: str) -> str:
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if not _TAX_ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Egyptian Tax ID must be 9 digits (e.g. 200-118-815): {value}"
        )
    return cleaned


def _normalize_company_number(value: str) -> str:
    cleaned = re.sub(r"[\s/]", "", value.strip().upper())
    if _LEI_RE.match(cleaned) or _CR_RE.match(cleaned):
        return cleaned
    raise InvalidIdentifierError(
        f"EG COMPANY_NUMBER must be a CR number (digits) or a 20-char LEI: {value}"
    )


async def _gleif_get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    async with build_http_client(base_url=_GLEIF_BASE, headers=_GLEIF_HEADERS) as client:
        resp = await get_with_retry(client, path, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def _record_by_cr(cr: str) -> dict[str, Any] | None:
    payload = await _gleif_get(
        "/lei-records",
        {
            "filter[entity.registeredAs]": cr,
            "filter[entity.legalAddress.country]": "EG",
            "page[size]": 5,
        },
    )
    records = (payload or {}).get("data") or []
    for record in records:
        entity = (record.get("attributes") or {}).get("entity") or {}
        if str(entity.get("registeredAs") or "") == cr:
            return record
    return records[0] if records else None


def _name_variants(record: dict[str, Any]) -> list[str]:
    entity = (record.get("attributes") or {}).get("entity") or {}
    names: list[str] = []
    legal = ((entity.get("legalName") or {}).get("name")) or ""
    if legal:
        names.append(legal)
    for key in ("otherNames", "transliteratedOtherNames"):
        for item in entity.get(key) or []:
            value = (item or {}).get("name")
            if value:
                names.append(value)
    for source in list(names):
        names.extend(_ACRONYM_RE.findall(source))
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.strip().upper()
        if key and key not in seen:
            seen.add(key)
            unique.append(name.strip())
    return unique


def _search_queries(names: list[str]) -> list[str]:
    queries: list[str] = []
    for name in names:
        cleaned = re.sub(r"\(.*?\)", " ", name)
        cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            continue
        tokens = cleaned.split()
        candidates = [cleaned]
        if tokens and tokens[-1].upper() == "EGYPT":
            candidates.append(" ".join(tokens[:-1]))
        for candidate in candidates:
            if candidate and candidate not in queries:
                queries.append(candidate)
    return queries


async def _ar_find_company(client: httpx.AsyncClient, query: str) -> tuple[str, str] | None:
    resp = await get_with_retry(
        client, "/Companies", params={"search": query}
    )
    if resp.status_code != 200:
        return None
    for match in _AR_RESULT_RE.finditer(resp.text):
        slug = match.group(1)
        label = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if "egypt" in label.lower():
            return slug, label
    return None


async def _pdf_downloads(url: str, client: httpx.AsyncClient) -> bool:
    try:
        resp = await client.get(url, headers={"Range": "bytes=0-15"})
    except (httpx.TransportError, httpx.TimeoutException):
        return False
    if resp.status_code not in (200, 206):
        return False
    ctype = resp.headers.get("content-type", "").lower()
    return "pdf" in ctype or resp.content[:5] == b"%PDF-"


class EGAdapter(CountryAdapter):
    country_code = "EG"
    country_name = "Egypt"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        try:
            payload = await _gleif_get(
                "/lei-records",
                {"filter[entity.legalAddress.country]": "EG", "page[size]": 1},
            )
            reachable = bool((payload or {}).get("data") is not None)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"GLEIF unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if reachable else AdapterStatus.ERROR,
            capabilities={"search": reachable, "lookup": reachable, "financials": reachable},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via GLEIF (CR in registeredAs). Filings via "
                "AnnualReports.com for covered issuers. GAFI/ETA/EGX are gated."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        payload = await _gleif_get(
            "/lei-records",
            {
                "filter[fulltext]": name,
                "filter[entity.legalAddress.country]": "EG",
                "page[size]": max(1, min(int(limit), 200)),
                "page[number]": 1,
            },
        )
        records = (payload or {}).get("data") or []
        matches = [_to_match(record) for record in records]
        return [m for m in matches if m is not None]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            _normalize_tax_id(value)
            raise AdapterNotImplementedError(
                "Egypt: VAT/Tax-ID lookup has no free source. GLEIF indexes the "
                "Commercial Registration number, not the ETA Tax ID."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"EG supports COMPANY_NUMBER and VAT, got {id_type}"
            )

        identifier = _normalize_company_number(value)
        if _LEI_RE.match(identifier):
            return await GLEIFClient().lookup_by_lei(identifier)

        record = await _record_by_cr(identifier)
        if record is None:
            return None
        lei = record.get("id")
        details = await GLEIFClient().lookup_by_lei(str(lei)) if lei else None
        if details is None:
            return None
        if not any(
            i.type == IdentifierType.COMPANY_NUMBER and i.value == identifier
            for i in details.identifiers
        ):
            details.identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=identifier,
                    label="CR Number",
                )
            )
        return details

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        names = await self._resolve_names(company_id)
        if not names:
            return []

        async with build_http_client(
            base_url=_AR_BASE,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"},
        ) as client:
            found: tuple[str, str] | None = None
            for query in _search_queries(names):
                found = await _ar_find_company(client, query)
                if found:
                    break
            if not found:
                return []

            slug, _label = found
            company_url = f"{_AR_BASE}/Company/{slug}"
            page = await get_with_retry(client, f"/Company/{slug}")
            if page.status_code != 200:
                return []

            seen_years: set[int] = set()
            candidates: list[tuple[int, str]] = []
            for match in _AR_PDF_RE.finditer(page.text):
                year = int(match.group(2))
                if year in seen_years:
                    continue
                seen_years.add(year)
                candidates.append((year, f"{_AR_BASE}{match.group(1)}"))
            candidates.sort(key=lambda item: item[0], reverse=True)

            filings: list[FinancialFiling] = []
            for year, pdf_url in candidates:
                if len(filings) >= max(1, years):
                    break
                if not await _pdf_downloads(pdf_url, client):
                    continue
                filings.append(
                    FinancialFiling(
                        company_id=company_id,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        currency="EGP",
                        document_url=pdf_url,
                        document_format="pdf",
                        source_url=company_url,
                    )
                )
            return filings

    async def _resolve_names(self, company_id: str) -> list[str]:
        candidate = re.sub(r"[\s/]", "", company_id.strip().upper())
        if _LEI_RE.match(candidate):
            details = await GLEIFClient().lookup_by_lei(candidate)
            return [details.name] if details else []
        if _CR_RE.match(candidate):
            record = await _record_by_cr(candidate)
            return _name_variants(record) if record else []
        return [company_id.strip()]


def _format_address(address: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for line in address.get("addressLines") or []:
        if line:
            parts.append(str(line))
    for key in ("city", "region", "postalCode", "country"):
        value = address.get(key)
        if value:
            parts.append(str(value))
    return ", ".join(p.strip() for p in parts if p and p.strip()) or None


def _to_match(record: dict[str, Any]) -> CompanyMatch | None:
    lei = record.get("id")
    entity = (record.get("attributes") or {}).get("entity") or {}
    name = ((entity.get("legalName") or {}).get("name")) or ""
    if not lei or not name:
        return None
    address = entity.get("legalAddress") or {}
    identifiers = [RegistryIdentifier(type=IdentifierType.LEI, value=str(lei))]
    registered_as = entity.get("registeredAs")
    if registered_as:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=str(registered_as),
                label="CR Number",
            )
        )
    status_raw = (entity.get("status") or "").upper()
    return CompanyMatch(
        id=str(lei),
        name=str(name),
        country=(address.get("country") or "EG").upper(),
        identifiers=identifiers,
        address=_format_address(address),
        status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
        source_url=f"https://search.gleif.org/#/record/{lei}",
    )
