"""Cyprus adapter — DRCOR (Department of Registrar of Companies and Official
Receiver) public search + VIES VAT validation.

Public free DRCOR search:
    https://efiling.drcor.mcit.gov.cy/DrcorPublic/SearchForm.aspx
    https://efiling.drcor.mcit.gov.cy/DrcorPublic/SearchResults.aspx
    https://efiling.drcor.mcit.gov.cy/DrcorPublic/ViewOrganisation.aspx?id={internal_id}

DRCOR is an ASP.NET WebForms application: name search and ID search both need
a POST that echoes `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, and `__EVENTVALIDATION`
back from a prior GET on the form page. We do exactly that with httpx; no
Playwright, no JS execution.

VAT lookups go through the EU VIES SOAP endpoint:
    https://ec.europa.eu/taxation_customs/vies/services/checkVatService

Filings are not freely available — DRCOR offers per-document electronic filings
only via authenticated paid access; we therefore return [] from
``fetch_financials``.

Identifiers:
- HE Number: ``HE`` + digits (up to 9). Stored normalized as bare digits,
  zero-padded to 9 (DRCOR's internal width).
- CY VAT: ``CY`` + 8 digits + 1 letter.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
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

logger = logging.getLogger(__name__)

_HE_RE = re.compile(r"^\d{1,9}$")
_VAT_RE = re.compile(r"^\d{8}[A-Z]$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HIDDEN_INPUT_RE = re.compile(
    r'<input[^>]+name="(__VIEWSTATE|__VIEWSTATEGENERATOR|__EVENTVALIDATION)"[^>]*value="([^"]*)"',
    re.IGNORECASE,
)


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


class CYAdapter(CountryAdapter):
    country_code = "CY"
    country_name = "Cyprus"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    DRCOR_BASE = "https://efiling.drcor.mcit.gov.cy"
    SEARCH_FORM = "/DrcorPublic/SearchForm.aspx?sc=0"
    SEARCH_RESULTS = "/DrcorPublic/SearchResults.aspx"
    VIEW_ORG = "/DrcorPublic/ViewOrganisation.aspx"

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.DRCOR_BASE) as client:
                resp = await get_with_retry(client, self.SEARCH_FORM)
                if resp.status_code >= 400:
                    raise AdapterError(
                        f"DRCOR search form returned {resp.status_code}"
                    )
                if "__VIEWSTATE" not in resp.text:
                    raise AdapterError(
                        "DRCOR search form missing __VIEWSTATE — page shape changed"
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
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "DRCOR scrape for name/HE lookup; VIES SOAP for VAT. "
                "Filings not freely available."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        return await self._drcor_search(name=name, he_number=None, limit=limit)

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
        # DRCOR e-filings require an authenticated paid account; nothing free
        # and machine-readable exists. Per project rules, prefer empty over
        # mock data.
        return []

    async def _drcor_search(
        self,
        *,
        name: str | None,
        he_number: str | None,
        limit: int,
    ) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.DRCOR_BASE) as client:
            form_resp = await get_with_retry(client, self.SEARCH_FORM)
            form_resp.raise_for_status()
            hidden = _extract_hidden_fields(form_resp.text)
            if "__VIEWSTATE" not in hidden:
                raise AdapterNotImplementedError(
                    "DRCOR search form shape unrecognized"
                )

            payload = {
                **hidden,
                "ctl00$cphMaster$ddlOrgType": "0",
                "ctl00$cphMaster$txtName": name or "",
                "ctl00$cphMaster$txtNumber": he_number or "",
                "ctl00$cphMaster$rbStartMatch": "optStartMatch",
                "ctl00$cphMaster$ddlOrgState": "0",
                "ctl00$cphMaster$btnSearch": "Search",
            }
            results_resp = await client.post(
                self.SEARCH_RESULTS,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{self.DRCOR_BASE}{self.SEARCH_FORM}",
                },
            )
            if results_resp.status_code >= 400:
                raise AdapterError(
                    f"DRCOR search returned {results_resp.status_code}"
                )
            html_text = results_resp.text

        return _parse_search_results(html_text, limit=limit)

    async def _drcor_lookup_by_he(self, he: str) -> CompanyDetails | None:
        matches = await self._drcor_search(name=None, he_number=he, limit=5)
        target_id = he.lstrip("0") or "0"
        match = None
        for m in matches:
            if (m.id or "").lstrip("0") == target_id:
                match = m
                break
        if match is None:
            return None

        internal_id = (match.source_url or "").split("id=")[-1] if "id=" in (
            match.source_url or ""
        ) else None
        raw: dict[str, Any] = {"match": match.model_dump(mode="json")}
        org_html: str | None = None
        if internal_id:
            async with build_http_client(base_url=self.DRCOR_BASE) as client:
                org_resp = await get_with_retry(
                    client, f"{self.VIEW_ORG}?id={internal_id}&lang=EN"
                )
                if org_resp.status_code < 400:
                    org_html = org_resp.text
                    raw["org_html_bytes"] = len(org_html)

        details_extra = _parse_view_organisation(org_html) if org_html else {}
        return CompanyDetails(
            id=he,
            name=match.name,
            country="CY",
            legal_form=details_extra.get("legal_form"),
            status=details_extra.get("status") or match.status,
            incorporation_date=details_extra.get("incorporation_date"),
            registered_address=details_extra.get("registered_address")
            or match.address,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=f"HE{int(he)}",
                    label="HE Number",
                ),
            ],
            raw=raw,
            source_url=match.source_url,
        )

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
                raise InvalidIdentifierError(
                    f"VIES rejected VAT CY{vat}"
                )
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


def _extract_hidden_fields(html_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for m in _HIDDEN_INPUT_RE.finditer(html_text):
        fields[m.group(1)] = unescape(m.group(2))
    return fields


_ROW_RE = re.compile(
    r"<tr[^>]*>(?P<row>.*?)</tr>", re.IGNORECASE | re.DOTALL
)
_CELL_RE = re.compile(r"<td[^>]*>(?P<cell>.*?)</td>", re.IGNORECASE | re.DOTALL)
_ORG_LINK_RE = re.compile(
    r'href="ViewOrganisation\.aspx\?id=([^"&]+)[^"]*"',
    re.IGNORECASE,
)


def _parse_search_results(html_text: str, *, limit: int) -> list[CompanyMatch]:
    matches: list[CompanyMatch] = []
    seen_ids: set[str] = set()
    for row_match in _ROW_RE.finditer(html_text):
        row = row_match.group("row")
        link_match = _ORG_LINK_RE.search(row)
        if not link_match:
            continue
        internal_id = link_match.group(1)
        cells = [_strip_html(c.group("cell")) for c in _CELL_RE.finditer(row)]
        cells = [c for c in cells if c]
        if not cells:
            continue
        he_number: str | None = None
        name: str | None = None
        org_type: str | None = None
        status: str | None = None
        for cell in cells:
            if he_number is None and re.fullmatch(r"\d{1,9}", cell):
                he_number = cell
                continue
            if name is None and any(ch.isalpha() for ch in cell):
                name = cell
                continue
            if org_type is None and len(cell) <= 40 and any(ch.isalpha() for ch in cell):
                org_type = cell
                continue
            if status is None:
                status = cell
        if not he_number or not name:
            continue
        bare = he_number.lstrip("0") or "0"
        if bare in seen_ids:
            continue
        seen_ids.add(bare)
        matches.append(
            CompanyMatch(
                id=he_number.zfill(9),
                name=name,
                country="CY",
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=f"HE{int(he_number)}",
                        label="HE Number",
                    ),
                ],
                status=status,
                source_url=(
                    f"https://efiling.drcor.mcit.gov.cy/DrcorPublic/"
                    f"ViewOrganisation.aspx?id={internal_id}&lang=EN"
                ),
            )
        )
        if len(matches) >= limit:
            break
    return matches


_VIEW_FIELD_RE = re.compile(
    r"<span[^>]*id=\"[^\"]*lbl([A-Za-z]+)\"[^>]*>(.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)


def _parse_view_organisation(html_text: str | None) -> dict[str, Any]:
    if not html_text:
        return {}
    fields: dict[str, str] = {}
    for m in _VIEW_FIELD_RE.finditer(html_text):
        key = m.group(1).lower()
        val = _strip_html(m.group(2))
        if val and key not in fields:
            fields[key] = val

    incorporation = _parse_date_eu(fields.get("registrationdate") or fields.get("regdate"))
    return {
        "legal_form": fields.get("organisationtype") or fields.get("orgtype"),
        "status": fields.get("organisationstatus") or fields.get("orgstatus"),
        "incorporation_date": incorporation,
        "registered_address": fields.get("address") or fields.get("registeredaddress"),
    }


def _parse_date_eu(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            from datetime import datetime as _dt

            return _dt.strptime(s, fmt).date()
        except ValueError:
            continue
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
