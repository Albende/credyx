"""Cyprus adapter — DRCOR (Department of Registrar of Companies and
Intellectual Property) public search + GLEIF/ESEF filings + VIES VAT.

DRCOR public search (free, no auth, no JS):
    https://efiling.drcor.mcit.gov.cy/DrcorPublic/SearchResults.aspx
The public results page is a plain GET keyed by query string — the search
form's ``__doPostBack`` merely 302-redirects to that URL, so we skip the
ASP.NET ViewState round-trip entirely and request SearchResults directly.
Results are a GridView; each row carries the (Latin) company name, the HE
registration number, organisation type, name status and organisation
status. Per-row detail pages sit behind a session-bound ``Select`` postback
that the public endpoint rejects, so we read everything from the row.

Financial filings come from the EU ESEF pipeline, entirely free and
key-free:
    HE number  ->  GLEIF ``registeredAs``  ->  LEI
    LEI        ->  filings.xbrl.org JSON:API  ->  ESEF annual reports
filings.xbrl.org hosts the actual iXBRL report packages (downloadable
``.zip``) for Cyprus-domiciled listed issuers. DRCOR's own e-filings are
paywalled and never used here.

VAT lookups go through the EU VIES SOAP endpoint.

Identifiers:
- HE Number: ``HE`` + digits (up to 9). Stored normalized as bare digits,
  zero-padded to 9 (DRCOR's internal width).
- CY VAT: ``CY`` + 8 digits + 1 letter.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from html import unescape
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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

logger = logging.getLogger(__name__)

_HE_RE = re.compile(r"^\d{1,9}$")
_VAT_RE = re.compile(r"^\d{8}[A-Z]$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_ORG_STATUS_MAP = {
    "εγγεγραμμ": "active",
    "διαλυθ": "dissolved",
    "διαλυμ": "dissolved",
    "διαγρα": "struck_off",
    "εκκαθαρ": "in_liquidation",
    "αναστ": "suspended",
    "παυση": "ceased",
}
_ORG_TYPE_MAP = {
    "εταιρεια": "Company",
    "αλλοδαπη": "Overseas company",
    "συνεταιρισμ": "Partnership",
    "εμπορικη επωνυμια": "Business name",
}
_CURRENT_NAME_MARKERS = ("τελευταιο",)
_COMPANY_TYPE_CODE = "ηε"


def _normalize_he(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned.startswith("HE"):
        cleaned = cleaned[2:]
    if not cleaned or not _HE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"CY HE number must be HE + up to 9 digits: {value}"
        )
    return cleaned.zfill(9)


def _normalize_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("CY"):
        cleaned = cleaned[2:]
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"CY VAT must be CY + 8 digits + 1 letter: {value}"
        )
    return cleaned


def _strip_html(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    text = unescape(text).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def _greek_key(text: str) -> str:
    lowered = unescape(text).lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS_RE.sub(" ", stripped)


def _map_org_status(raw: str | None) -> str | None:
    if not raw:
        return None
    key = _greek_key(raw)
    for prefix, mapped in _ORG_STATUS_MAP.items():
        if key.startswith(prefix):
            return mapped
    return raw


def _map_org_type(raw: str | None) -> str | None:
    if not raw:
        return None
    key = _greek_key(raw)
    for needle, mapped in _ORG_TYPE_MAP.items():
        if needle in key:
            return mapped
    return raw


def _is_current_name(name_status: str | None) -> bool:
    if not name_status:
        return False
    key = _greek_key(name_status)
    return any(marker in key for marker in _CURRENT_NAME_MARKERS)


class CYAdapter(CountryAdapter):
    country_code = "CY"
    country_name = "Cyprus"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    DRCOR_BASE = "https://efiling.drcor.mcit.gov.cy"
    SEARCH_RESULTS = "/DrcorPublic/SearchResults.aspx"

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    XBRL_FILINGS_BASE = "https://filings.xbrl.org"

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.DRCOR_BASE) as client:
                resp = await get_with_retry(
                    client, self._results_url(name="%", number="165")
                )
                if resp.status_code >= 400:
                    raise AdapterError(
                        f"DRCOR search returned {resp.status_code}"
                    )
                if "GridView1" not in resp.text:
                    raise AdapterError(
                        "DRCOR results missing GridView1 — page shape changed"
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "DRCOR public GET for name/HE lookup; VIES SOAP for VAT; "
                "ESEF filings via GLEIF -> filings.xbrl.org."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        html_text = await self._drcor_get(name=name.strip(), number="%")
        return _parse_search_results(html_text, limit=limit)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            he = _normalize_he(value)
            return await self._drcor_lookup_by_he(he)
        if id_type == IdentifierType.VAT:
            vat = _normalize_vat(value)
            return await self._vies_lookup(vat)
        raise InvalidIdentifierError(
            f"CY supports COMPANY_NUMBER or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        he = _normalize_he(company_id)
        lei = await self._gleif_lei_for_he(he.lstrip("0") or "0")
        if not lei:
            return []
        return await self._xbrl_filings_for_lei(lei, he=he, years=years)

    def _results_url(self, *, name: str, number: str) -> str:
        from urllib.parse import quote

        return (
            f"{self.SEARCH_RESULTS}?name={quote(name)}&number={quote(number)}"
            "&searchtype=optStartMatch&index=1&tname=%25&sc=0"
        )

    async def _drcor_get(self, *, name: str, number: str) -> str:
        async with build_http_client(base_url=self.DRCOR_BASE) as client:
            resp = await get_with_retry(client, self._results_url(name=name, number=number))
            if resp.status_code >= 400:
                raise AdapterError(f"DRCOR search returned {resp.status_code}")
            return resp.text

    async def _drcor_lookup_by_he(self, he: str) -> CompanyDetails | None:
        target = he.lstrip("0") or "0"
        html_text = await self._drcor_get(name="%", number=target)
        rows = _parse_result_rows(html_text)
        rows = [
            r
            for r in rows
            if (r["number"] or "").lstrip("0") == target
            and _greek_key(r["type_code"] or "") == _COMPANY_TYPE_CODE
        ]
        if not rows:
            return None

        current = next((r for r in rows if _is_current_name(r["name_status"])), rows[0])
        previous_names = [
            r["name"]
            for r in rows
            if r["name"] and r["name"] != current["name"]
        ]
        raw: dict[str, Any] = {"rows": rows}
        if previous_names:
            raw["previous_names"] = previous_names

        return CompanyDetails(
            id=he,
            name=current["name"],
            country="CY",
            legal_form=_map_org_type(current["org_type"]),
            status=_map_org_status(current["org_status"]),
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=f"HE{int(he)}",
                    label="HE Number",
                ),
            ],
            raw=raw,
            source_url=(
                f"{self.DRCOR_BASE}{self._results_url(name='%', number=target)}"
            ),
        )

    async def _gleif_lei_for_he(self, he_digits: str) -> str | None:
        params = {
            "filter[entity.registeredAs]": he_digits,
            "filter[entity.legalAddress.country]": "CY",
            "page[size]": 10,
        }
        async with build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()

        for record in payload.get("data") or []:
            entity = (record.get("attributes") or {}).get("entity") or {}
            registered_as = entity.get("registeredAs") or ""
            if re.sub(r"\D", "", registered_as) == he_digits:
                lei = record.get("id")
                if lei:
                    return str(lei)
        return None

    async def _xbrl_filings_for_lei(
        self, lei: str, *, he: str, years: int
    ) -> list[FinancialFiling]:
        params = {
            "filter[entity.identifier]": lei,
            "sort": "-period_end",
            "page[size]": max(1, min(int(years) * 2, 20)),
        }
        async with build_http_client(
            base_url=self.XBRL_FILINGS_BASE,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, "/api/filings", params=params)
            resp.raise_for_status()
            payload = resp.json()

        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for record in payload.get("data") or []:
            attrs = record.get("attributes") or {}
            period_end = _parse_iso_date(attrs.get("period_end"))
            if not period_end or period_end.year in seen_years:
                continue
            seen_years.add(period_end.year)
            package_url = attrs.get("package_url")
            viewer_url = attrs.get("viewer_url") or attrs.get("report_url")
            filings.append(
                FinancialFiling(
                    company_id=he,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="EUR",
                    document_url=(
                        f"{self.XBRL_FILINGS_BASE}{package_url}"
                        if package_url
                        else None
                    ),
                    document_format="xbrl",
                    source_url=(
                        f"{self.XBRL_FILINGS_BASE}{viewer_url}"
                        if viewer_url
                        else f"{self.XBRL_FILINGS_BASE}/#/?entity={lei}"
                    ),
                )
            )
            if len(filings) >= years:
                break
        return filings

    async def _vies_lookup(self, vat: str) -> CompanyDetails | None:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope '
            'xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">'
            "<soapenv:Header/><soapenv:Body>"
            "<urn:checkVat>"
            "<urn:countryCode>CY</urn:countryCode>"
            f"<urn:vatNumber>{vat}</urn:vatNumber>"
            "</urn:checkVat>"
            "</soapenv:Body></soapenv:Envelope>"
        )
        async with build_http_client() as client:
            resp = await client.post(
                self.VIES_URL,
                content=envelope,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "",
                },
            )
            if resp.status_code >= 500:
                raise AdapterError(f"VIES returned {resp.status_code}")
            if resp.status_code == 400 or "INVALID_INPUT" in resp.text:
                raise InvalidIdentifierError(f"VIES rejected VAT CY{vat}")
            resp.raise_for_status()
            body = resp.text

        if "<valid>false</valid>" in body or "<ns2:valid>false</ns2:valid>" in body:
            return None
        if "<valid>true</valid>" not in body and "<ns2:valid>true</ns2:valid>" not in body:
            return None

        name = _xml_text(body, "name")
        address = _xml_text(body, "address")
        return CompanyDetails(
            id=f"CY{vat}",
            name=name or f"CY{vat}",
            country="CY",
            status="active",
            registered_address=address,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=f"CY{vat}", label="VAT"
                ),
            ],
            raw={"vies_xml_bytes": len(body)},
            source_url="https://ec.europa.eu/taxation_customs/vies/",
        )


_BASKET_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*basket[^"]*"[^>]*>(?P<row>.*?)</tr>',
    re.IGNORECASE | re.DOTALL,
)
_CELL_RE = re.compile(r"<td[^>]*>(?P<cell>.*?)</td>", re.IGNORECASE | re.DOTALL)


def _parse_result_rows(html_text: str) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for row_match in _BASKET_ROW_RE.finditer(html_text):
        cells = [_strip_html(c.group("cell")) for c in _CELL_RE.finditer(row_match.group("row"))]
        if len(cells) < 7:
            continue
        name = cells[1]
        number = cells[3]
        if not name or not re.fullmatch(r"\d{1,9}", number or ""):
            continue
        rows.append(
            {
                "name": name,
                "type_code": cells[2] or None,
                "number": number,
                "org_type": cells[4] or None,
                "name_status": cells[5] or None,
                "org_status": cells[6] or None,
            }
        )
    return rows


def _parse_search_results(html_text: str, *, limit: int) -> list[CompanyMatch]:
    by_key: dict[str, dict[str, str | None]] = {}
    order: list[str] = []
    for row in _parse_result_rows(html_text):
        bare = (row["number"] or "").lstrip("0") or "0"
        key = f"{_greek_key(row['type_code'] or '')}:{bare}"
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = row
            order.append(key)
        elif _is_current_name(row["name_status"]) and not _is_current_name(
            existing["name_status"]
        ):
            by_key[key] = row

    matches: list[CompanyMatch] = []
    for key in order:
        row = by_key[key]
        number = row["number"] or ""
        bare = number.lstrip("0") or "0"
        matches.append(
            CompanyMatch(
                id=number.zfill(9),
                name=row["name"],
                country="CY",
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=f"HE{int(number)}",
                        label="HE Number",
                    ),
                ],
                status=_map_org_status(row["org_status"]),
                source_url=(
                    "https://efiling.drcor.mcit.gov.cy/DrcorPublic/"
                    f"SearchResults.aspx?name=%25&number={bare}"
                    "&searchtype=optStartMatch&index=1&tname=%25&sc=0"
                ),
            )
        )
        if len(matches) >= limit:
            break
    return matches


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _xml_text(body: str, tag: str) -> str | None:
    pattern = re.compile(
        rf"<(?:ns2:)?{tag}>(.*?)</(?:ns2:)?{tag}>", re.IGNORECASE | re.DOTALL
    )
    m = pattern.search(body)
    if not m:
        return None
    raw = m.group(1).strip()
    if not raw or raw == "---":
        return None
    return _WS_RE.sub(" ", unescape(raw)).strip()


__all__ = ["CYAdapter"]
