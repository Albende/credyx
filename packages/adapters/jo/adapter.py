"""Jordan adapter — Amman Stock Exchange (ASE) listed-issuer data.

The official companies register (Companies Control Department, CCD, at
https://www.ccd.gov.jo/) is an Arabic-only ASP.NET WebForms portal with
no free JSON/REST contract and no bulk export, so it cannot back a live
adapter without an interactive session replay. The Amman Stock Exchange
— https://www.exchange.jo/ (formerly www.ase.com.jo) — is the
authoritative *free* structured source for Jordanian listed companies and
is what this adapter uses:

* ``/en/products-services/securties-types/shares`` is a public directory
  of every listed share issuer (English + Arabic long/short name, ASE
  ticker symbol, numeric security code, paid-up capital, market segment).
  It backs ``search_by_name`` and ``lookup_by_identifier``.
* ``/en/disclosures?symbol={TICKER}&category_id=1`` lists an issuer's
  filed *Annual Financial Report* disclosures, each with a downloadable
  audited-statements document (PDF or ZIP). It backs ``fetch_financials``.

Per the project rules this adapter never fabricates data. Companies that
are not ASE-listed have no free Jordanian source, so name search simply
returns no match for them and ``fetch_financials`` returns ``[]``.

Identifiers:

* ``OTHER`` — the ASE ticker symbol (e.g. ``JOPH``). Primary key across
  search, lookup, and financials.
* ``COMPANY_NUMBER`` — the ASE numeric security code (e.g. ``141018``).
  Accepted by ``lookup_by_identifier`` as a secondary key.
"""
from __future__ import annotations

import re
from datetime import date, datetime

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

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,8}$")
_CODE_RE = re.compile(r"^\d{3,10}$")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(
    r'views-field-([a-z0-9-]+)">\s*(?:<a[^>]*>)?\s*([^<]*)', re.S
)
_PUBLISHED_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

_MARKETS = {"1": "ASE First Market", "2": "ASE Second Market", "3": "ASE Third Market"}
_ANNUAL_REPORT_CATEGORY = "1"


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_capital(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


class _Listing:
    __slots__ = ("symbol", "code", "name", "name_short", "capital", "market")

    def __init__(
        self,
        *,
        symbol: str,
        code: str,
        name: str,
        name_short: str,
        capital: str,
        market: str,
    ) -> None:
        self.symbol = symbol
        self.code = code
        self.name = name
        self.name_short = name_short
        self.capital = capital
        self.market = market


class JOAdapter(CountryAdapter):
    country_code = "JO"
    country_name = "Jordan"
    identifier_types = [IdentifierType.OTHER, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.OTHER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    ASE_BASE = "https://www.exchange.jo"
    SHARES_PATH = "/en/products-services/securties-types/shares"
    DISCLOSURES_PATH = "/en/disclosures"

    async def _load_listings(self) -> list[_Listing]:
        async with build_http_client(base_url=self.ASE_BASE, timeout=30.0) as client:
            resp = await get_with_retry(client, self.SHARES_PATH)
            resp.raise_for_status()
            html = resp.text

        listings: list[_Listing] = []
        for raw_row in _ROW_RE.findall(html):
            fields = dict(_CELL_RE.findall(raw_row))
            symbol = fields.get("symbol-1", "").strip().upper()
            if not symbol:
                continue
            listings.append(
                _Listing(
                    symbol=symbol,
                    code=fields.get("code", "").strip(),
                    name=_collapse_ws(fields.get("name-long", "")),
                    name_short=_collapse_ws(fields.get("name-short", "")),
                    capital=fields.get("capital", "").strip(),
                    market=fields.get("market-id", "").strip(),
                )
            )
        return listings

    def _company_url(self, symbol: str) -> str:
        return f"{self.ASE_BASE}{self.DISCLOSURES_PATH}?symbol={symbol}"

    def _to_details(self, listing: _Listing) -> CompanyDetails:
        return CompanyDetails(
            id=listing.symbol,
            name=listing.name or listing.name_short or listing.symbol,
            country="JO",
            legal_form=_MARKETS.get(listing.market),
            status="listed",
            capital_amount=_parse_capital(listing.capital),
            capital_currency="JOD",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=listing.symbol,
                    label="ASE ticker symbol",
                ),
                *(
                    [
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=listing.code,
                            label="ASE security code",
                        )
                    ]
                    if listing.code
                    else []
                ),
            ],
            raw={
                "symbol": listing.symbol,
                "code": listing.code,
                "name_short": listing.name_short,
                "capital": listing.capital,
                "market_id": listing.market,
            },
            source_url=self._company_url(listing.symbol),
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.ASE_BASE, timeout=10.0) as client:
                resp = await get_with_retry(client, self.SHARES_PATH, max_attempts=1)
                reachable = 200 <= resp.status_code < 500
        except Exception:
            reachable = False

        status = AdapterStatus.OK if reachable else AdapterStatus.ERROR
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={
                "search": reachable,
                "lookup": reachable,
                "financials": reachable,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "ASE-listed issuers only: directory + annual-report filings "
                "from exchange.jo. CCD/MIT name search and ISTD TRN lookup "
                "remain gated (Arabic-only ASP.NET, no public JSON)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = _collapse_ws(name).lower()
        if not needle:
            return []

        matches: list[CompanyMatch] = []
        for listing in await self._load_listings():
            haystack = f"{listing.name} {listing.name_short}".lower()
            if needle not in haystack:
                continue
            identifiers = [
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=listing.symbol,
                    label="ASE ticker symbol",
                )
            ]
            if listing.code:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=listing.code,
                        label="ASE security code",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=listing.symbol,
                    name=listing.name or listing.name_short or listing.symbol,
                    country="JO",
                    identifiers=identifiers,
                    status="listed",
                    source_url=self._company_url(listing.symbol),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        needle = re.sub(r"[\s\-]", "", value.strip())
        if id_type == IdentifierType.OTHER:
            key = needle.upper()
            if not _SYMBOL_RE.match(key):
                raise InvalidIdentifierError(
                    f"Jordan ASE ticker symbol must be 2-8 alphanumerics, got: {value}"
                )
            for listing in await self._load_listings():
                if listing.symbol == key:
                    return self._to_details(listing)
            return None

        if id_type == IdentifierType.COMPANY_NUMBER:
            if not _CODE_RE.match(needle):
                raise InvalidIdentifierError(
                    f"Jordan ASE security code must be 3-10 digits, got: {value}"
                )
            for listing in await self._load_listings():
                if listing.code == needle:
                    return self._to_details(listing)
            return None

        raise InvalidIdentifierError(
            f"Jordan supports OTHER (ASE ticker) and COMPANY_NUMBER "
            f"(ASE security code), got {id_type}"
        )

    async def _resolve_symbol(self, company_id: str) -> str | None:
        key = re.sub(r"[\s\-]", "", company_id.strip()).upper()
        if _CODE_RE.match(key):
            for listing in await self._load_listings():
                if listing.code == key:
                    return listing.symbol
            return None
        return key if _SYMBOL_RE.match(key) else None

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        symbol = await self._resolve_symbol(company_id)
        if not symbol:
            return []

        params = {"symbol": symbol, "category_id": _ANNUAL_REPORT_CATEGORY}
        async with build_http_client(base_url=self.ASE_BASE, timeout=30.0) as client:
            resp = await get_with_retry(client, self.DISCLOSURES_PATH, params=params)
            resp.raise_for_status()
            html = resp.text

        source_url = f"{self.ASE_BASE}{self.DISCLOSURES_PATH}?symbol={symbol}&category_id={_ANNUAL_REPORT_CATEGORY}"
        body = html[html.find("<tbody") : html.rfind("</tbody")]

        best_by_year: dict[int, tuple[date, str, str]] = {}
        for raw_row in _ROW_RE.findall(body):
            published = _PUBLISHED_RE.search(
                _field(raw_row, "views-field-published")
            )
            if not published:
                continue
            day, month, pub_year = (int(g) for g in published.groups())
            published_on = date(pub_year, month, day)

            doc_url, doc_format = _document_link(raw_row)
            if not doc_url:
                continue

            fiscal_year = pub_year - 1
            existing = best_by_year.get(fiscal_year)
            if existing is None or published_on > existing[0]:
                best_by_year[fiscal_year] = (published_on, doc_url, doc_format)

        filings: list[FinancialFiling] = []
        for fiscal_year in sorted(best_by_year, reverse=True)[:years]:
            _published_on, doc_url, doc_format = best_by_year[fiscal_year]
            filings.append(
                FinancialFiling(
                    company_id=symbol,
                    year=fiscal_year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=None,
                    currency="JOD",
                    structured_data=None,
                    document_url=f"{self.ASE_BASE}{doc_url}",
                    document_format=doc_format,
                    source_url=source_url,
                )
            )
        return filings


def _field(row: str, css_class: str) -> str:
    match = re.search(rf'{css_class}">(.*?)</td>', row, re.S)
    return match.group(1) if match else ""


def _document_link(row: str) -> tuple[str | None, str | None]:
    for css_class, fmt in (
        ("views-field-filename", "pdf"),
        ("views-field-filename-zip", "zip"),
        ("views-field-filename-xls", "xls"),
    ):
        cell = _field(row, css_class)
        href = re.search(r'href="([^"]+)"', cell)
        if href:
            return href.group(1), fmt
    return None, None
