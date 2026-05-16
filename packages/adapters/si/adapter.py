"""Slovenia adapter — AJPES (Agencija RS za javnopravne evidence in storitve).

Sources:
- eObjave (court-register publications): https://www.ajpes.si/eObjave/
  Public, no auth. Returns name + matična številka (registration number) +
  davčna številka (tax/VAT) for each filing. Used as the canonical identifier
  source because it exposes both IDs together in plain HTML rows.
- JOLP (Javna objava letnih poročil): https://www.ajpes.si/jolp/
  Public name/identifier search returns address + postcode + city. The
  individual annual-report PDFs require AJPES free-but-registered login —
  scraping them needs a session and is deferred to Phase 2.
- ePRS company detail pages and AJPES financial-statement (FI-PO) figures
  are gated behind login and not used here.

Approach: HTML scraping with stdlib re only (no bs4/lxml dependency). The
result tables on rezultati.asp use a stable per-row pattern of
`<a href="objava.asp?...&id={id}">{value}</a>` cells in a fixed column
order, which is sturdy enough for MVP. Defensive parsing — if a layout
change breaks a row we skip it rather than crash.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote_plus

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
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

_MATICNA_RE = re.compile(r"^\d{10}$")
_DAVCNA_RE = re.compile(r"^\d{8}$")

# eObjave result rows: each <tr> has 6 <td> cells, several of which wrap an
# `<a href="objava.asp?s=...&id=N">VALUE</a>` link with the field value. We
# extract the row block then pull the named anchor groups.
_ROW_BLOCK_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_BLOCK_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_ANCHOR_TEXT_RE = re.compile(r">\s*([^<]+?)\s*<", re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

# JOLP result row column order: name (link), address, postcode, city, court,
# vlozna številka.
_JOLP_ROW_RE = re.compile(
    r'<a\s+href="podjetje\.asp\?maticna=(?P<mat>\d{10})">\s*'
    r"(?P<name>[^<]+?)\s*</a>"
    r"(?P<rest>.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_maticna(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if not _MATICNA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"SI Matična številka must be 10 digits, got: {value}"
        )
    return cleaned


def _normalize_davcna(value: str) -> str:
    cleaned = value.strip().replace(" ", "").upper()
    if cleaned.startswith("SI"):
        cleaned = cleaned[2:]
    if not _DAVCNA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"SI Davčna številka (VAT) must be 8 digits, got: {value}"
        )
    return cleaned


def _strip(text: str) -> str:
    return html.unescape(_TAG_STRIP_RE.sub("", text)).strip()


class SIAdapter(CountryAdapter):
    country_code = "SI"
    country_name = "Slovenia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    EOB_BASE = "https://www.ajpes.si/eObjave"
    JOLP_BASE = "https://www.ajpes.si/jolp"
    # id_skupina=48 = court-register publication index (splošni vpis), the
    # broadest public stream covering every active SI business subject.
    EOB_GROUP = 48

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.EOB_BASE) as client:
                resp = await get_with_retry(client, "/default.asp", params={"s": self.EOB_GROUP})
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "AJPES eObjave + JOLP public scrape. Financial PDFs require "
                "AJPES registered session (Phase 2)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._eobjave_search(firma=name)
        seen: set[str] = set()
        matches: list[CompanyMatch] = []
        for row in rows:
            mat = row.get("maticna")
            if not mat or mat in seen:
                continue
            seen.add(mat)
            vat = row.get("davcna")
            idents = [
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=mat,
                    label="Matična številka",
                )
            ]
            if vat:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=f"SI{vat}",
                        label="Davčna številka",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=mat,
                    name=row.get("firma", ""),
                    country=self.country_code,
                    identifiers=idents,
                    address=None,
                    status=None,
                    source_url=self._eobjave_link_for(mat),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            params: dict[str, Any] = {"Maticna": _normalize_maticna(value)}
        elif id_type == IdentifierType.VAT:
            params = {"Davcna": _normalize_davcna(value)}
        else:
            raise InvalidIdentifierError(
                f"SI only supports COMPANY_NUMBER (Matična) or VAT (Davčna), got {id_type}"
            )

        rows = await self._eobjave_search(**params)
        if not rows:
            return None

        first = rows[0]
        mat = first.get("maticna") or ""
        vat = first.get("davcna")
        firma = first.get("firma", "")
        if not mat:
            return None

        address = await self._jolp_address_for(mat)

        idents = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=mat,
                label="Matična številka",
            )
        ]
        if vat:
            idents.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=f"SI{vat}",
                    label="Davčna številka",
                )
            )

        return CompanyDetails(
            id=mat,
            name=firma,
            country=self.country_code,
            legal_form=None,
            status=None,
            registered_address=address,
            capital_currency="EUR",
            identifiers=idents,
            raw={"eobjave_first_row": first, "jolp_address": address},
            source_url=self._eobjave_link_for(mat),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        _normalize_maticna(company_id)
        raise AdapterNotImplementedError(
            "AJPES annual-report PDFs (JOLP) and FI-PO structured figures are "
            "gated behind a free-but-registered session. Browser-pool scraping "
            "is a Phase 2 task — see docs/countries/si.md."
        )

    def _eobjave_link_for(self, maticna: str) -> str:
        return (
            f"{self.EOB_BASE}/rezultati.asp?"
            f"podrobno=0&id_skupina={self.EOB_GROUP}&Maticna={maticna}"
        )

    async def _eobjave_search(self, **params: Any) -> list[dict[str, str]]:
        q = {"podrobno": "0", "id_skupina": str(self.EOB_GROUP)}
        for k, v in params.items():
            if v is None:
                continue
            q[k] = str(v)
        async with build_http_client(base_url=self.EOB_BASE) as client:
            resp = await get_with_retry(client, "/rezultati.asp", params=q)
            resp.raise_for_status()
            return _parse_eobjave_rows(resp.text)

    async def _jolp_address_for(self, maticna: str) -> str | None:
        url = f"/rezultati.asp?maticna={quote_plus(maticna)}&podrobno=0"
        async with build_http_client(base_url=self.JOLP_BASE) as client:
            resp = await get_with_retry(client, url)
            if resp.status_code != 200:
                return None
            return _parse_jolp_address(resp.text, maticna)


def _parse_eobjave_rows(html_text: str) -> list[dict[str, str]]:
    """Extract rows from an eObjave rezultati.asp results table.

    Each row's six <td> cells are: datum objave, vrsta, firma, matična,
    davčna, srg številka. Several cells wrap the value inside an anchor —
    we strip tags + entities to get the plain text.
    """
    # Slice to the results <tbody> if present; otherwise scan the whole page.
    body_start = html_text.lower().find("<tbody>")
    body_end = html_text.lower().find("</tbody>", body_start + 1)
    region = (
        html_text[body_start:body_end] if body_start != -1 and body_end != -1 else html_text
    )
    out: list[dict[str, str]] = []
    for row_match in _ROW_BLOCK_RE.finditer(region):
        cells = _TD_BLOCK_RE.findall(row_match.group(1))
        if len(cells) < 6:
            continue
        date_s = _strip(cells[0])
        vrsta = _strip(cells[1])
        firma = _strip(cells[2])
        maticna = _strip(cells[3])
        davcna = _strip(cells[4])
        srg = _strip(cells[5])
        if not _MATICNA_RE.match(maticna):
            continue
        out.append(
            {
                "datum": date_s,
                "vrsta": vrsta,
                "firma": firma,
                "maticna": maticna,
                "davcna": davcna if _DAVCNA_RE.match(davcna) else "",
                "srg": srg,
            }
        )
    return out


def _parse_jolp_address(html_text: str, maticna: str) -> str | None:
    """Pull the (street, postcode, city) of the matching JOLP result row.

    JOLP result rows look like:
        <a href="podjetje.asp?maticna=NNNN">NAME</a></td>
        <td valign="top">Šmarješka cesta 6 </td>
        <td valign="top">8000</td>
        <td valign="top">Novo mesto</td>
    Returns "<street>, <postcode> <city>" or None if not found.
    """
    for m in _JOLP_ROW_RE.finditer(html_text):
        if m.group("mat") != maticna:
            continue
        rest = m.group("rest")
        cells = _TD_BLOCK_RE.findall(rest)
        if len(cells) < 3:
            return None
        street = _strip(cells[0])
        postcode = _strip(cells[1])
        city = _strip(cells[2])
        parts = [p for p in [street, f"{postcode} {city}".strip()] if p]
        return ", ".join(parts) or None
    return None


def _coerce_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None
