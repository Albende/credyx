"""Bosnia and Herzegovina adapter.

BiH has no single company register: incorporation records live in three
separate court/agency systems (Federation of BiH court registry, Republika
Srpska APIF, Brčko District), none of which exposes a free machine-readable
API — the FBiH portal is a stateful Oracle APEX app and the RS bizreg host
is offline.

The one free, no-auth, structured live source that covers real Bosnian
companies with both registry detail *and* filed financial statements is the
**Banja Luka Stock Exchange** (``blberza.com``). It publishes, for every
issuer traded on the RS capital market:

* an issuer-name autocomplete service (JSON) — used for name search,
* an issuer profile page (address, contact, ownership) — used for lookup,
* an unaudited financial-statements page sourced from APIF — used for
  financials (real filed balance sheets, not synthesized numbers).

Issuers are keyed by their exchange code (e.g. ``TLKM`` for Telekom Srpske);
that code is this adapter's ``COMPANY_NUMBER``. Coverage is therefore RS
listed/registered issuers; FBiH-only private companies are not reachable
without the paid court registry and surface as empty results, never mock
data.
"""
from __future__ import annotations

import json
import re
from datetime import date
from html import unescape

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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
    Shareholder,
)

_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,12}$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_YEAR_OPT_RE = re.compile(r'value="(\d{4})"')

_PAGE_NOT_FOUND = "requested page does not exist"

_SECTION_HEADINGS = {
    "podaci o emitentu",
    "vlasnička struktura",
    "deset najvećih akcionara",
    "područje djelatnosti",
    "lice ovlašćeno za zastupanje",
    "upravni odbor",
    "nadzorni odbor",
    "registar emitenata",
    "grafikoni",
    "cijene",
    "poslovi",
    "objave",
    "finansijski izvještaji",
    "podaci o hartiji",
}

_BALANCE_SHEET_LABELS = {
    "stalna sredstva": "non_current_assets",
    "tekuća sredstva": "current_assets",
    "gotovinski ekvivalenti i gotovina": "cash",
    "bilansna aktiva": "total_assets",
    "kapital": "total_equity",
    "osnovni kapital": "share_capital",
    "rezerve": "reserves",
    "neraspoređeni dobitak": "retained_earnings",
    "dugoročne obaveze": "non_current_liabilities",
    "kratkoročne obaveze": "current_liabilities",
}


def _normalize_code(value: str) -> str:
    cleaned = value.strip().upper()
    if not _CODE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"BA issuer code must be 2-12 alphanumerics (e.g. TLKM): {value!r}"
        )
    return cleaned


def _strip_html(fragment: str) -> str:
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", fragment))).strip()


def _cells(row_html: str) -> list[str]:
    return [_strip_html(c) for c in _CELL_RE.findall(row_html)]


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9,.\-]", "", value).replace(".", "").replace(",", ".")
    if digits in {"", "-", "."}:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _status_from_name(name: str) -> str:
    low = name.lower()
    if "u stečaju" in low or "u stecaju" in low:
        return "Bankruptcy (u stečaju)"
    if "u likvidaciji" in low:
        return "Liquidation (u likvidaciji)"
    return "Listed"


def _legal_form_from_name(name: str) -> str | None:
    low = f" {name.lower()} "
    if "akcionarsko društvo" in low or " a.d." in low or " ad " in low:
        return "Akcionarsko društvo (a.d.)"
    if "društvo sa ograničenom" in low or " d.o.o." in low:
        return "Društvo sa ograničenom odgovornošću (d.o.o.)"
    return None


class BAAdapter(CountryAdapter):
    country_code = "BA"
    country_name = "Bosnia and Herzegovina"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    BLSE_BASE = "https://www.blberza.com"
    AUTOCOMPLETE_PATH = (
        "/Code/Services/Autocompleter/IssuerListAutocompleterService.ashx"
    )

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BLSE_BASE,
            timeout=30.0,
            headers={"Accept": "text/html,application/json;q=0.9,*/*;q=0.5"},
        )

    def _issuer_url(self, code: str) -> str:
        return f"{self.BLSE_BASE}/Pages/IssuerData.aspx?code={code}"

    def _reports_url(self, code: str) -> str:
        return f"{self.BLSE_BASE}/Pages/FinancialReports.aspx?code={code}"

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, self.AUTOCOMPLETE_PATH, params={"q": "a"})
                if resp.status_code >= 500:
                    raise AdapterError(f"BLSE autocomplete HTTP {resp.status_code}")
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
                "Live source: Banja Luka Stock Exchange (blberza.com). Covers "
                "RS capital-market issuers; FBiH-only private firms not reachable "
                "via a free API."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client, self.AUTOCOMPLETE_PATH, params={"q": query}
                )
                if resp.status_code != 200:
                    return []
                rows = json.loads(resp.text)
        except (httpx.HTTPError, json.JSONDecodeError):
            return []

        matches: list[CompanyMatch] = []
        for entry in rows:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            code, company_name = str(entry[0]).strip(), str(entry[1]).strip()
            if not code or not company_name:
                continue
            matches.append(
                CompanyMatch(
                    id=code,
                    name=company_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=code,
                            label="BLSE issuer code",
                        )
                    ],
                    status=_status_from_name(company_name),
                    source_url=self._issuer_url(code),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"BA lookup uses COMPANY_NUMBER (BLSE issuer code), got {id_type}"
            )
        code = _normalize_code(value)
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, f"/Pages/IssuerData.aspx?code={code}")
                if resp.status_code != 200:
                    return None
                html = resp.text
        except httpx.HTTPError:
            return None

        if _PAGE_NOT_FOUND in html.lower():
            return None
        name = _extract_issuer_name(html)
        if not name or "unknown issuer" in name.lower():
            return None

        tokens = _tokenize(html)
        address = _labeled(tokens, "Adresa")
        phone = _labeled(tokens, "Telefon")
        website = _labeled(tokens, "Web")
        email = _labeled(tokens, "Email")
        security_code = _labeled(tokens, "Emisije emitenata")
        activity = _labeled(tokens, "Područje")
        shareholders = _extract_shareholders(html)

        raw: dict[str, object] = {"source": "BLSE", "issuer_code": code}
        if security_code:
            raw["security_code"] = security_code
        if activity:
            raw["activity"] = activity

        return CompanyDetails(
            id=code,
            name=name,
            country=self.country_code,
            legal_form=_legal_form_from_name(name),
            status=_status_from_name(name),
            registered_address=address,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=code,
                    label="BLSE issuer code",
                )
            ],
            shareholders=shareholders,
            website=website,
            phone=phone,
            email=email,
            raw=raw,
            source_url=self._issuer_url(code),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        code = _normalize_code(company_id)
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client, f"/Pages/FinancialReports.aspx?code={code}"
                )
                if resp.status_code != 200:
                    return []
                html = resp.text
        except httpx.HTTPError:
            return []

        if _PAGE_NOT_FOUND in html.lower():
            return []

        available = _available_annual_years(html)
        if not available:
            return []
        balance_sheets = _parse_balance_sheets(html)

        reports_url = self._reports_url(code)
        filings: list[FinancialFiling] = []
        for year in available[:years]:
            bs = balance_sheets.get(year)
            structured = None
            if bs:
                structured = {
                    "currency": "BAM",
                    "source": "APIF via Banja Luka Stock Exchange (unaudited)",
                    "statement": "abbreviated_balance_sheet",
                    "balance_sheet": bs,
                }
            filings.append(
                FinancialFiling(
                    company_id=code,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="BAM",
                    structured_data=structured,
                    document_url=None,
                    document_format="html" if structured else None,
                    source_url=reports_url,
                )
            )
        return filings


def _extract_issuer_name(html: str) -> str:
    for raw in _H1_RE.findall(html):
        text = _strip_html(raw)
        if text and text.lower() not in _SECTION_HEADINGS:
            return text
    return ""


def _tokenize(html: str) -> list[str]:
    parts = unescape(_TAG_RE.sub("\n", html)).split("\n")
    return [_WS_RE.sub(" ", p).strip() for p in parts if p.strip()]


_FIELD_LABELS = {
    "adresa", "telefon", "web", "email", "emisije emitenata",
    "područje", "oblast", "vlasnička struktura",
}


def _labeled(tokens: list[str], label: str) -> str | None:
    for i, tok in enumerate(tokens):
        if tok == label and i + 1 < len(tokens):
            value = tokens[i + 1].strip()
            if not value or value.lower() in _FIELD_LABELS:
                return None
            return value
    return None


def _extract_shareholders(html: str) -> list[Shareholder]:
    anchor = html.lower().find("deset najve")
    if anchor < 0:
        return []
    segment = html[anchor:anchor + 6000]
    holders: list[Shareholder] = []
    for row_html in _ROW_RE.findall(segment):
        cells = [c for c in _cells(row_html) if c]
        if len(cells) < 2:
            continue
        name = cells[0]
        if name.lower() in {"naziv", "% učešća", "% ucesca"}:
            continue
        percent = _parse_amount(cells[1])
        if percent is None:
            continue
        holders.append(Shareholder(name=name, percent=percent))
        if len(holders) >= 10:
            break
    return holders


def _available_annual_years(html: str) -> list[int]:
    match = re.search(r'ddlGodisnji"[^>]*>(.*?)</select>', html, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    years = [int(y) for y in _YEAR_OPT_RE.findall(match.group(1))]
    return sorted(set(years), reverse=True)


def _parse_balance_sheets(html: str) -> dict[int, dict[str, float]]:
    per_year: dict[int, dict[str, float]] = {}
    col_years: list[int] = []
    for row_html in _ROW_RE.findall(html):
        cells = [c for c in _cells(row_html) if c]
        if not cells:
            continue
        head = cells[0].lower()
        if head.startswith("skra") and "bilans" in head:
            col_years = [int(c) for c in cells[1:] if re.fullmatch(r"\d{4}", c)]
            continue
        if not col_years:
            continue
        key = _BALANCE_SHEET_LABELS.get(cells[0].lower())
        if not key or len(cells) < 1 + len(col_years):
            continue
        for year, raw_value in zip(col_years, cells[1:1 + len(col_years)]):
            amount = _parse_amount(raw_value)
            if amount is not None:
                per_year.setdefault(year, {})[key] = amount
    return per_year


def _parse_ba_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for sep in (".", "/", "-"):
        if sep in value:
            parts = [p for p in value.split(sep) if p]
            if len(parts) >= 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2][:4])
                    return date(y, m, d)
                except ValueError:
                    continue
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
