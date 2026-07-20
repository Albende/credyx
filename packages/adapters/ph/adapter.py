"""Philippines adapter — PSE Edge (Philippine Stock Exchange disclosure portal).

The SEC's former public viewer (`iview.sec.gov.ph`) was retired and no longer
resolves, and the SEC's replacement search portals (eSPARC / eSEARCH) sit
behind a bot wall and forbid automated scraping in their terms. The only
free, no-auth, machine-readable Philippine source that returns real
company data — including downloadable audited financial statements — is
**PSE Edge**, the Philippine Stock Exchange's disclosure portal.

Coverage is therefore **PSE-listed companies** (the large-cap universe:
SM, AC, BDO, JFC, URC, …). For unlisted Philippine companies there is no
free official machine-readable source, so `search_by_name` returns only
listed matches and never fabricates a record.

Sources (all on `https://edge.pse.com.ph`, no API key):

* `/autoComplete/searchCompanyNameSymbol.ax?term=` — JSON company search,
  returns `{cmpyId, cmpyNm, symbol}` rows. Backs `search_by_name`.
* `/companyInformation/form.do?cmpy_id=` — the company profile page
  (sector, incorporation date, registered office, auditor, website).
  Backs `lookup_by_identifier`.
* `/companyDisclosures/search.ax` (POST, `keyword={cmpy_id}`,
  `tmplNm=Annual Report`) — the company's filed annual reports (SEC Form
  17-A). Each row links to a disclosure viewer whose attachments are the
  real 17-A PDF + audited financial statements. Backs `fetch_financials`.

Identifier: `COMPANY_NUMBER` carries the **PSE ticker symbol** (e.g. `SM`,
`AC`, `JFC`) — the key PSE Edge uses to address a company. It is the only
stable public handle exposed by this source.
"""
from __future__ import annotations

import re
from datetime import date, datetime
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

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
_FY_RE = re.compile(
    r"(?:(?:31\s*)?dec(?:ember)?\s*[,]?\s*(\d{4})"
    r"|december\s*31\s*[,]?\s*(\d{4})"
    r"|as\s*of\s*[^0-9]{0,20}(\d{4}))",
    re.IGNORECASE,
)
_LEADING_YEAR_RE = re.compile(r"^\s*(\d{4})\b")
_ANNOUNCE_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _normalize_symbol(value: str) -> str:
    cleaned = value.strip().upper()
    if cleaned.startswith("PSE:"):
        cleaned = cleaned[4:].strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    if not _SYMBOL_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Philippines PSE ticker symbol invalid: {value}"
        )
    return cleaned


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class PHAdapter(CountryAdapter):
    country_code = "PH"
    country_name = "Philippines"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    PSE_BASE = "https://edge.pse.com.ph"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
            "Accept-Language": "en;q=0.9",
            "Referer": f"{self.PSE_BASE}/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.PSE_BASE, headers=self._headers()
            ) as client:
                resp = await get_with_retry(
                    client,
                    "/autoComplete/searchCompanyNameSymbol.ax",
                    params={"term": "SM"},
                )
                if resp.status_code != 200:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": False,
                        },
                        notes=f"PSE Edge HTTP {resp.status_code}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "PSE Edge (no auth). Covers PSE-listed companies: search + "
                "profile + filed 17-A annual reports with downloadable PDFs."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        rows = await self._autocomplete(query)
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            symbol = str(r.get("symbol") or "").strip().upper()
            display = str(r.get("cmpyNm") or "").strip()
            if not symbol or not display:
                continue
            matches.append(
                CompanyMatch(
                    id=symbol,
                    name=display,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=symbol,
                            label="PSE Company Symbol",
                        ),
                    ],
                    source_url=(
                        f"{self.PSE_BASE}/companyPage/stockData.do"
                        f"?cmpy_id={str(r.get('cmpyId') or '').strip()}"
                    ),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Philippines supports COMPANY_NUMBER (PSE symbol), got {id_type}"
            )
        symbol = _normalize_symbol(value)
        resolved = await self._resolve_symbol(symbol)
        if resolved is None:
            return None
        cmpy_id = str(resolved.get("cmpyId") or "").strip()
        display = str(resolved.get("cmpyNm") or "").strip()
        fields = await self._company_information(cmpy_id)
        return self._to_details(symbol, cmpy_id, display, fields)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        symbol = _normalize_symbol(company_id)
        resolved = await self._resolve_symbol(symbol)
        if resolved is None:
            return []
        cmpy_id = str(resolved.get("cmpyId") or "").strip()
        reports = await self._annual_reports(cmpy_id)
        if not reports:
            return []

        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        async with build_http_client(
            base_url=self.PSE_BASE, headers=self._headers()
        ) as client:
            for edge_no, announce in reports:
                if len(filings) >= years:
                    break
                company_name, attachments = await self._disclosure_files(
                    client, edge_no
                )
                if company_name and symbol not in company_name.upper() and (
                    resolved.get("cmpyNm", "").upper() not in company_name.upper()
                ):
                    continue
                file_id, label = _pick_annual_pdf(attachments)
                fiscal_year = _fiscal_year(label, announce)
                if fiscal_year is None or fiscal_year in seen_years:
                    continue
                seen_years.add(fiscal_year)
                filings.append(
                    FinancialFiling(
                        company_id=symbol,
                        year=fiscal_year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(fiscal_year, 12, 31),
                        currency="PHP",
                        document_url=(
                            f"{self.PSE_BASE}/downloadFile.do?file_id={file_id}"
                            if file_id
                            else None
                        ),
                        document_format="pdf" if file_id else None,
                        source_url=(
                            f"{self.PSE_BASE}/openDiscViewer.do?edge_no={edge_no}"
                        ),
                    )
                )
        return filings

    async def _autocomplete(self, term: str) -> list[dict[str, Any]]:
        async with build_http_client(
            base_url=self.PSE_BASE, headers=self._headers()
        ) as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/autoComplete/searchCompanyNameSymbol.ax",
                    params={"term": term},
                )
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if resp.status_code != 200:
                return []
            try:
                payload = resp.json()
            except ValueError:
                return []
            if isinstance(payload, list):
                return [r for r in payload if isinstance(r, dict)]
            return []

    async def _resolve_symbol(self, symbol: str) -> dict[str, Any] | None:
        rows = await self._autocomplete(symbol)
        for r in rows:
            if str(r.get("symbol") or "").strip().upper() == symbol:
                return r
        return None

    async def _company_information(self, cmpy_id: str) -> dict[str, str]:
        if not cmpy_id:
            return {}
        async with build_http_client(
            base_url=self.PSE_BASE, headers=self._headers()
        ) as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/companyInformation/form.do",
                    params={"cmpy_id": cmpy_id, "security_id": cmpy_id},
                )
            except (httpx.TransportError, httpx.TimeoutException):
                return {}
            if resp.status_code != 200:
                return {}
            return _parse_info_table(resp.text or "")

    async def _annual_reports(self, cmpy_id: str) -> list[tuple[str, str]]:
        if not cmpy_id:
            return []
        async with build_http_client(
            base_url=self.PSE_BASE, headers=self._headers()
        ) as client:
            try:
                resp = await client.post(
                    "/companyDisclosures/search.ax",
                    data={
                        "keyword": cmpy_id,
                        "tmplNm": "Annual Report",
                        "sortType": "date",
                        "dateSortType": "DESC",
                        "cmpySortType": "ASC",
                        "pageNo": "",
                    },
                )
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if resp.status_code != 200:
                return []
            return _parse_disclosure_rows(resp.text or "")

    async def _disclosure_files(
        self, client: httpx.AsyncClient, edge_no: str
    ) -> tuple[str | None, list[tuple[str, str]]]:
        try:
            resp = await client.get(
                "/openDiscViewer.do", params={"edge_no": edge_no}
            )
        except (httpx.TransportError, httpx.TimeoutException):
            return None, []
        if resp.status_code != 200:
            return None, []
        html = resp.text or ""
        company = re.search(r"<h2>(.*?)</h2>", html, re.S)
        company_name = _strip_tags(company.group(1)) if company else None
        attachments = [
            (fid, _strip_tags(label))
            for fid, label in re.findall(
                r'<option value="(\d+)">(.*?)</option>', html, re.S
            )
        ]
        return company_name, attachments

    def _to_details(
        self,
        symbol: str,
        cmpy_id: str,
        display_name: str,
        fields: dict[str, str],
    ) -> CompanyDetails:
        inc_date = _parse_ph_date(fields.get("Incorporation Date"))
        sector = fields.get("Sector")
        subsector = fields.get("Subsector")
        sic_codes = [s for s in dict.fromkeys([sector, subsector]) if s]
        return CompanyDetails(
            id=symbol,
            name=display_name or fields.get("Company Name") or symbol,
            country="PH",
            legal_form=sector,
            status="active",
            incorporation_date=inc_date,
            registered_address=fields.get("Business Address"),
            capital_amount=None,
            capital_currency="PHP",
            sic_codes=sic_codes,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=symbol,
                    label="PSE Company Symbol",
                ),
            ],
            raw={"cmpy_id": cmpy_id, **fields},
            source_url=(
                f"{self.PSE_BASE}/companyPage/stockData.do?cmpy_id={cmpy_id}"
            ),
        )


def _parse_info_table(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in re.findall(r"<tr>.*?</tr>", html, re.S):
        cells = [
            _strip_tags(c)
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
        ]
        cells = [c for c in cells if c]
        if len(cells) == 2 and len(cells[0]) < 60:
            fields[cells[0]] = cells[1]
    return fields


def _parse_disclosure_rows(html: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in re.findall(r"<tr>.*?</tr>", html, re.S):
        if "openPopup" not in tr:
            continue
        edge = re.search(r"openPopup\('([^']+)'\)", tr)
        if not edge:
            continue
        cells = [
            _strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        ]
        announce = cells[1] if len(cells) > 1 else ""
        rows.append((edge.group(1), announce))
    return rows


def _pick_annual_pdf(
    attachments: list[tuple[str, str]],
) -> tuple[str | None, str]:
    if not attachments:
        return None, ""
    for fid, label in attachments:
        lo = label.lower()
        if "17-a" in lo or "17a" in lo or "annual report" in lo:
            return fid, label
    fid, label = attachments[0]
    return fid, label


def _fiscal_year(label: str, announce: str) -> int | None:
    if label:
        m = _FY_RE.search(label)
        if m:
            year = next((g for g in m.groups() if g), None)
            if year:
                return int(year)
        lead = _LEADING_YEAR_RE.match(label)
        if lead:
            return int(lead.group(1))
    years = _ANNOUNCE_YEAR_RE.findall(announce or "")
    if years:
        return int(years[-1]) - 1
    return None


def _parse_ph_date(s: Any) -> date | None:
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
