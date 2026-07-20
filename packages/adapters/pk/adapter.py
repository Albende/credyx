"""Pakistan adapter — PSX Data Portal (listed companies).

Sources
-------
- PSX Data Portal symbol directory (JSON, free, no key):
    https://dps.psx.com.pk/symbols
- PSX Data Portal per-company page (HTML, free, no key):
    https://dps.psx.com.pk/company/{SYMBOL}
  Carries a company profile, key people, an annual/quarterly financials
  table with filed figures, and an announcements table linking the real
  annual-report PDFs the company transmitted to the exchange.

The Securities & Exchange Commission of Pakistan (SECP) eServices name
search and the FBR NTN inquiry are ASP.NET ViewState + CAPTCHA gated with
no free programmatic path, so unlisted-company lookup by Incorporation
Number and NTN is surfaced as `AdapterNotImplementedError` (501) rather
than faked. Listed companies — the entities that matter for credit work —
are fully served from the PSX Data Portal.

Identifiers
-----------
- Incorporation Number — variable-length numeric SECP id. Primary type.
  A PSX trading symbol (short alpha token, e.g. ``HBL``) is accepted on
  the same identifier slot and routed to the working PSX path.
- NTN (National Tax Number) — FBR tax id; mapped to ``IdentifierType.VAT``.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date

import httpx

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
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)


_INC_NUMBER_RE = re.compile(r"^\d{1,10}$")
_NTN_RE = re.compile(r"^\d{7,8}(-\d)?$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_TAG_RE = re.compile(r"<[^>]+>")
_PERIOD_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2})\s*,?\s*(\d{4})"
)


def normalize_incorporation_number(value: str) -> str:
    """Strip whitespace and validate the numeric Incorporation Number."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _INC_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Pakistan Incorporation Number must be 1-10 digits, got {value!r}"
        )
    return cleaned.zfill(7)


def normalize_ntn(value: str) -> str:
    """Strip whitespace and validate the FBR NTN."""
    cleaned = value.strip().replace(" ", "")
    if not _NTN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Pakistan NTN must be 7-8 digits (optional -check), got {value!r}"
        )
    return cleaned


def _strip_tags(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", fragment)).strip()


def _slice_between(source: str, start_marker: str, *end_markers: str) -> str | None:
    start = source.find(start_marker)
    if start < 0:
        return None
    tail = source[start + len(start_marker):]
    end = len(tail)
    for marker in end_markers:
        pos = tail.find(marker)
        if 0 <= pos < end:
            end = pos
    return tail[:end]


def _parse_number(raw: str) -> float | int | None:
    text = _strip_tags(raw).replace(",", "").strip()
    if not text or text in {"-", "N/A", "--"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("%", "")
    try:
        value = float(text)
    except ValueError:
        return None
    if negative:
        value = -value
    return int(value) if value.is_integer() else value


def _parse_period_end(title: str) -> date | None:
    match = _PERIOD_RE.search(title)
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if not month:
        return None
    day, year = int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


class PKAdapter(CountryAdapter):
    country_code = "PK"
    country_name = "Pakistan"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    PSX_BASE = "https://dps.psx.com.pk"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.PSX_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Referer": f"{self.PSX_BASE}/",
            },
        )

    async def _fetch_symbols(self, client: httpx.AsyncClient) -> list[dict]:
        resp = await get_with_retry(client, "/symbols", max_attempts=3)
        resp.raise_for_status()
        return json.loads(resp.text)

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, "/symbols", max_attempts=2)
                ok = resp.status_code < 500
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
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Coverage is PSX-listed companies via the PSX Data Portal "
                "(search, profile, filed financials, annual-report PDFs). "
                "Unlisted SECP/FBR lookup is CAPTCHA-gated and returns 501."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = name.strip().lower()
        if not needle:
            return []
        async with self._client() as client:
            symbols = await self._fetch_symbols(client)

        scored: list[tuple[int, CompanyMatch]] = []
        for entry in symbols:
            symbol = entry.get("symbol", "")
            company_name = entry.get("name", "")
            if not symbol or not company_name:
                continue
            if needle in company_name.lower() or needle == symbol.lower():
                is_instrument = bool(entry.get("isDebt") or entry.get("isETF"))
                exact_symbol = needle == symbol.lower()
                rank = (0 if exact_symbol else 1, 1 if is_instrument else 0)
                scored.append(
                    (
                        rank,
                        CompanyMatch(
                            id=symbol,
                            name=company_name,
                            country=self.country_code,
                            identifiers=[
                                RegistryIdentifier(
                                    type=IdentifierType.OTHER,
                                    value=symbol,
                                    label="PSX Symbol",
                                )
                            ],
                            status="listed",
                            source_url=f"{self.PSX_BASE}/company/{symbol}",
                        ),
                    )
                )
        if scored:
            scored.sort(key=lambda pair: pair[0])
            return [match for _, match in scored[:limit]]
        raise AdapterNotImplementedError(
            "No PSX-listed company matched. SECP eServices name search for "
            "unlisted companies is CAPTCHA + ViewState gated and unavailable "
            "for free. See docs/countries/pk.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            ntn = normalize_ntn(value)
            raise AdapterNotImplementedError(
                f"FBR NTN inquiry ({ntn}) is CAPTCHA-gated at e.fbr.gov.pk. "
                "Use a PSX symbol for listed companies."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"PK supports COMPANY_NUMBER (Incorporation Number / PSX "
                f"symbol) and VAT (NTN), got {id_type}"
            )

        raw = value.strip().upper()
        if _SYMBOL_RE.match(raw) and not raw.isdigit():
            async with self._client() as client:
                symbols = await self._fetch_symbols(client)
                entry = next((e for e in symbols if e.get("symbol") == raw), None)
                if entry is None:
                    raise InvalidIdentifierError(
                        f"{raw!r} is not a listed PSX symbol. Free PK coverage "
                        "is limited to PSX-listed companies."
                    )
                page = await self._fetch_company_page(client, raw)
            return self._details_from_page(raw, entry, page)

        inc = normalize_incorporation_number(raw)
        raise AdapterNotImplementedError(
            f"SECP Incorporation Number {inc} lookup needs the eServices "
            "authenticated session (CAPTCHA + ViewState); not available for "
            "free. Free PK coverage is PSX-listed companies via PSX symbol."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        symbol = company_id.strip().upper()
        if not (_SYMBOL_RE.match(symbol) and not symbol.isdigit()):
            raise AdapterNotImplementedError(
                "Financials are available only for PSX-listed companies "
                "(by PSX symbol). SECP filings for unlisted companies are not "
                "free. See docs/countries/pk.md."
            )
        async with self._client() as client:
            page = await self._fetch_company_page(client, symbol)

        annual = self._parse_annual_financials(page)
        pdf_by_year = self._parse_annual_report_pdfs(page)
        source_url = f"{self.PSX_BASE}/company/{symbol}"

        filings: list[FinancialFiling] = []
        for year in sorted(annual, reverse=True)[:years]:
            metrics = annual[year]
            pdf = pdf_by_year.get(year)
            filings.append(
                FinancialFiling(
                    company_id=symbol,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=(pdf["period_end"] if pdf else date(year, 12, 31)),
                    currency="PKR",
                    structured_data={
                        "metrics": metrics,
                        "unit": "PKR thousands (EPS in PKR per share)",
                    },
                    document_url=(pdf["url"] if pdf else None),
                    document_format=("pdf" if pdf else None),
                    source_url=source_url,
                )
            )
        return filings

    async def _fetch_company_page(
        self, client: httpx.AsyncClient, symbol: str
    ) -> str:
        resp = await get_with_retry(client, f"/company/{symbol}", max_attempts=3)
        resp.raise_for_status()
        return resp.text

    def _details_from_page(
        self, symbol: str, entry: dict, page: str
    ) -> CompanyDetails:
        name = entry.get("name") or self._extract_quote_name(page) or symbol
        sector = entry.get("sectorName") or None
        description = self._extract_business_description(page)
        directors = self._extract_key_people(page)
        raw: dict = {"psx_symbol": symbol}
        if sector:
            raw["sector"] = sector
        if description:
            raw["business_description"] = description
        return CompanyDetails(
            id=symbol,
            name=name,
            country=self.country_code,
            legal_form="Public Limited Company (Listed)",
            status="listed",
            sic_codes=[],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=symbol,
                    label="PSX Symbol",
                ),
            ],
            directors=directors,
            raw=raw,
            source_url=f"{self.PSX_BASE}/company/{symbol}",
            capital_currency="PKR",
        )

    @staticmethod
    def _extract_quote_name(page: str) -> str | None:
        match = re.search(r'class="quote__name"[^>]*>(.*?)<', page)
        return html.unescape(match.group(1)).strip() if match else None

    @staticmethod
    def _extract_business_description(page: str) -> str | None:
        block = _slice_between(page, "BUSINESS DESCRIPTION", "profile__item")
        if not block:
            return None
        para = re.search(r"<p>(.*?)</p>", block, re.S)
        if not para:
            return None
        text = _strip_tags(para.group(1))
        return text or None

    @staticmethod
    def _extract_key_people(page: str) -> list[Director]:
        block = _slice_between(page, "profile__item--people", "</table>")
        if not block:
            return []
        people: list[Director] = []
        for row in re.findall(r"<tr>(.*?)</tr>", block, re.S):
            cells = [_strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            cells = [c for c in cells if c]
            if not cells:
                continue
            name = cells[0]
            role = cells[1] if len(cells) > 1 else None
            people.append(Director(name=name, role=role))
        return people

    @staticmethod
    def _parse_annual_financials(page: str) -> dict[int, dict[str, float | int]]:
        section = _slice_between(page, 'id="financials"', 'id="reports"', 'id="profile"')
        if section is None:
            return {}
        panel = _slice_between(
            section, 'tabs__panel" data-name="Annual"', 'tabs__panel" data-name="Quarterly"'
        )
        if panel is None:
            return {}
        header = re.search(r"<thead[^>]*>(.*?)</tr>", panel, re.S)
        if not header:
            header = re.search(r"<tr>(.*?)</tr>", panel, re.S)
        if not header:
            return {}
        years: list[int] = []
        for th in re.findall(r"<th[^>]*>(.*?)</th>", header.group(1), re.S):
            text = _strip_tags(th)
            if re.fullmatch(r"\d{4}", text):
                years.append(int(text))
        if not years:
            return {}

        result: dict[int, dict[str, float | int]] = {y: {} for y in years}
        body = _slice_between(panel, "tbl__body", "</table>") or panel
        for row in re.findall(r"<tr>(.*?)</tr>", body, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 2:
                continue
            label = _strip_tags(cells[0])
            if not label or re.fullmatch(r"\d{4}", label):
                continue
            for idx, year in enumerate(years, start=1):
                if idx >= len(cells):
                    break
                number = _parse_number(cells[idx])
                if number is not None:
                    result[year][label] = number
        return {y: m for y, m in result.items() if m}

    @staticmethod
    def _parse_annual_report_pdfs(page: str) -> dict[int, dict]:
        panel = _slice_between(
            page,
            'tabs__panel" data-name="Financial Results"',
            'tabs__panel" data-name="Board Meetings"',
        )
        if panel is None:
            return {}
        result: dict[int, dict] = {}
        for row in re.findall(r"<tr>(.*?)</tr>", panel, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 3:
                continue
            title = _strip_tags(cells[1])
            if "annual report" not in title.lower():
                continue
            period_end = _parse_period_end(title)
            if not period_end:
                continue
            href = re.search(r'href="(/download/[^"]+\.pdf)"', row)
            if not href:
                continue
            result.setdefault(
                period_end.year,
                {
                    "url": f"https://dps.psx.com.pk{href.group(1)}",
                    "period_end": period_end,
                    "title": title,
                },
            )
        return result


__all__ = [
    "PKAdapter",
    "normalize_incorporation_number",
    "normalize_ntn",
]
