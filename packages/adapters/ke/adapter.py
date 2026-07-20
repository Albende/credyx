"""Kenya adapter — Nairobi Securities Exchange (NSE) issuer disclosures.

The official registry sources for private companies are gated:

- **BRS (Business Registration Service)** via eCitizen requires a logged-in
  account and charges per extract; there is no free JSON search API.
- **KRA iTax PIN checker** is an ASP.NET form behind ViewState + CAPTCHA.

The **NSE** runs on WordPress and exposes a fully public, key-free REST API
(``/wp-json/wp/v2``) that we use as the live data source:

- ``nse_timeline_event`` is the register of listed issuers (name + slug) —
  drives ``search_by_name`` and ``lookup_by_identifier``.
- ``media`` indexes every issuer disclosure PDF (audited/unaudited results,
  annual reports) with title + upload date + direct ``source_url`` — drives
  ``fetch_financials`` with real, downloadable filings.

Coverage is therefore the ~50 NSE-listed issuers (the largest Kenyan
corporates by market cap). Non-listed companies have no free filings source;
BRS/KRA lookups by ``COMPANY_NUMBER``/``VAT`` remain gated and raise.

Identifiers:
- ``OTHER``: the NSE issuer slug (e.g. ``safaricom-plc``) — the primary,
  free-to-resolve identifier.
- ``COMPANY_NUMBER``: BRS registration number (gated).
- ``VAT``: KRA PIN — ``[A|P]NNNNNNNNNL`` (gated).
"""
from __future__ import annotations

import html
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_KRA_PIN_RE = re.compile(r"^[AP]\d{9}[A-Z]$")
_BRS_NUMBER_RE = re.compile(r"^[A-Z]{2,4}[-/]?[A-Z0-9]{5,12}$")

_NSE_BASE = "https://www.nse.co.ke"
_WP_API = f"{_NSE_BASE}/wp-json/wp/v2"
_ANNOUNCEMENTS_URL = f"{_NSE_BASE}/listed-company-announcements/"

_GENERIC_TOKENS = {
    "plc",
    "ltd",
    "limited",
    "group",
    "holdings",
    "company",
    "co",
    "the",
    "kenya",
    "and",
    "&",
    "i-reit",
    "reit",
}

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DATE_NAME_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})[\s\-,.]+(\d{4})",
    re.IGNORECASE,
)
_DATE_NUM_RE = re.compile(r"(\d{1,2})[\-/](\d{1,2})[\-/](\d{4})")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_FILING_INCLUDE = ("result", "financial statement", "annual report")
_FILING_EXCLUDE = (
    "calendar", "forward looking", "forward-looking", "board", "director",
    "dividend", "agm", "appointment", "notice", "cautionary", "acquisition",
    "resolution", "secretary", "circular", "book closure", "rights issue",
    "profit warning", "change", "delay", "publication", "prospectus",
    "trading statement", "closed period", "suspension", "de-listing",
)


def _clean_name(rendered: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", rendered)).strip()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", html.unescape(value).lower()).strip("-")
    return slug


def _search_term(company_id: str) -> str:
    tokens = re.split(r"[\s\-_]+", html.unescape(company_id).lower())
    kept = [t for t in tokens if t and t not in _GENERIC_TOKENS]
    if not kept:
        kept = [t for t in tokens if t]
    return " ".join(kept[:4])


def _legal_form(name: str) -> str | None:
    upper = name.upper()
    if "REIT" in upper:
        return "Real Estate Investment Trust"
    if upper.endswith("PLC") or " PLC" in upper:
        return "Public Limited Company"
    if "LIMITED" in upper or upper.endswith("LTD") or " LTD" in upper:
        return "Limited Company"
    return None


def _parse_period(title: str) -> date | None:
    m = _DATE_NAME_RE.search(title)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
        if month and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    m = _DATE_NUM_RE.search(title)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _filing_type(title_lower: str) -> FilingType:
    if "annual report" in title_lower:
        return FilingType.ANNUAL_REPORT
    is_unaudited = bool(re.search(r"un[\s\-]?audited", title_lower))
    if not is_unaudited and "audited" in title_lower and "year ended" in title_lower:
        return FilingType.ANNUAL_REPORT
    return FilingType.BALANCE_SHEET


def _is_financial_filing(title_lower: str) -> bool:
    if any(bad in title_lower for bad in _FILING_EXCLUDE):
        return False
    return any(good in title_lower for good in _FILING_INCLUDE)


class KEAdapter(CountryAdapter):
    country_code = "KE"
    country_name = "Kenya"
    identifier_types = [
        IdentifierType.OTHER,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.VAT,
    ]
    primary_identifier = IdentifierType.OTHER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        reachable = False
        note = ""
        try:
            async with build_http_client(timeout=12.0) as client:
                resp = await get_with_retry(
                    client,
                    f"{_WP_API}/nse_timeline_event",
                    params={"per_page": 1, "_fields": "id"},
                    max_attempts=1,
                )
                reachable = resp.status_code < 400
                if not reachable:
                    note = f"NSE REST API HTTP {resp.status_code}"
        except Exception as exc:
            note = f"NSE REST API unreachable: {str(exc)[:120]}"

        if not reachable:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=note,
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Coverage: NSE-listed issuers via the public WordPress REST API "
                "(search, lookup, filing PDFs). Non-listed companies (BRS/KRA) "
                "remain gated behind login + CAPTCHA + paid extracts."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if len(query) < 2:
            raise InvalidIdentifierError(
                "Kenya name search requires at least 2 characters."
            )
        async with build_http_client(timeout=20.0) as client:
            events = await self._get_json(
                client,
                f"{_WP_API}/nse_timeline_event",
                params={
                    "search": query,
                    "per_page": max(1, min(limit, 50)),
                    "_fields": "id,slug,title,link",
                },
            )
            matches = [self._match_from_event(ev) for ev in events if ev.get("slug")]
            if matches:
                return matches[:limit]

            term = _search_term(query)
            media = await self._get_json(
                client,
                f"{_WP_API}/media",
                params={"search": term, "per_page": 20, "_fields": "title,source_url"},
            )
        has_filing = any(
            str(m.get("source_url", "")).lower().endswith(".pdf")
            and _is_financial_filing(_clean_name(m.get("title", {}).get("rendered", "")).lower())
            for m in media
        )
        if not has_filing:
            return []
        clean = _clean_name(query)
        slug = _slugify(query)
        return [
            CompanyMatch(
                id=slug,
                name=clean,
                country="KE",
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.OTHER, value=slug, label="NSE issuer"
                    )
                ],
                status="Listed (Nairobi Securities Exchange)",
                source_url=_ANNOUNCEMENTS_URL,
            )
        ]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            cleaned = value.strip().upper().replace(" ", "")
            if id_type is IdentifierType.VAT and not _KRA_PIN_RE.match(cleaned):
                raise InvalidIdentifierError(
                    f"KRA PIN must match [A|P]NNNNNNNNNX, got: {value}"
                )
            if id_type is IdentifierType.COMPANY_NUMBER and not _BRS_NUMBER_RE.match(
                cleaned
            ):
                raise InvalidIdentifierError(
                    f"BRS registration number format unrecognized: {value}"
                )
            raise AdapterNotImplementedError(
                "Kenya BRS (COMPANY_NUMBER) and KRA iTax (VAT) lookups require a "
                "logged-in eCitizen session / CAPTCHA and paid extracts. Use the "
                "NSE issuer slug (OTHER) for free listed-company lookups."
            )
        if id_type is not IdentifierType.OTHER:
            raise InvalidIdentifierError(
                f"Kenya supports OTHER (NSE slug), COMPANY_NUMBER, or VAT, got {id_type}"
            )

        slug = _slugify(value)
        async with build_http_client(timeout=20.0) as client:
            events = await self._get_json(
                client,
                f"{_WP_API}/nse_timeline_event",
                params={"slug": slug, "_fields": "id,slug,title,link"},
            )
            if not events:
                events = await self._get_json(
                    client,
                    f"{_WP_API}/nse_timeline_event",
                    params={
                        "search": _search_term(value),
                        "per_page": 1,
                        "_fields": "id,slug,title,link",
                    },
                )
            if not events:
                media = await self._get_json(
                    client,
                    f"{_WP_API}/media",
                    params={
                        "search": _search_term(value),
                        "per_page": 20,
                        "_fields": "title,source_url",
                    },
                )
                has_filing = any(
                    str(m.get("source_url", "")).lower().endswith(".pdf")
                    and _is_financial_filing(
                        _clean_name(m.get("title", {}).get("rendered", "")).lower()
                    )
                    for m in media
                )
                if not has_filing:
                    return None
                name = _clean_name(value)
                return CompanyDetails(
                    id=slug,
                    name=name,
                    country="KE",
                    legal_form=_legal_form(name),
                    status="Listed on the Nairobi Securities Exchange",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.OTHER, value=slug, label="NSE issuer"
                        )
                    ],
                    raw={"source": "nse.co.ke/wp-json/wp/v2/media", "slug": slug},
                    source_url=_ANNOUNCEMENTS_URL,
                )

        event = events[0]
        name = _clean_name(event.get("title", {}).get("rendered", ""))
        resolved_slug = event.get("slug") or slug
        return CompanyDetails(
            id=resolved_slug,
            name=name,
            country="KE",
            legal_form=_legal_form(name),
            status="Listed on the Nairobi Securities Exchange",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=resolved_slug,
                    label="NSE issuer",
                )
            ],
            raw={
                "source": "nse.co.ke/wp-json/wp/v2/nse_timeline_event",
                "post_id": event.get("id"),
                "slug": resolved_slug,
            },
            source_url=event.get("link") or _ANNOUNCEMENTS_URL,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        term = _search_term(company_id)
        if not term:
            return []
        async with build_http_client(timeout=25.0) as client:
            media = await self._get_json(
                client,
                f"{_WP_API}/media",
                params={
                    "search": term,
                    "per_page": 60,
                    "orderby": "date",
                    "order": "desc",
                    "_fields": "date,title,source_url,mime_type",
                },
            )

        best_by_year: dict[int, FinancialFiling] = {}
        for item in media:
            source_url = str(item.get("source_url", ""))
            if not source_url.lower().endswith(".pdf"):
                continue
            title = _clean_name(item.get("title", {}).get("rendered", ""))
            title_lower = title.lower()
            if not _is_financial_filing(title_lower):
                continue
            period_end = _parse_period(title)
            year: int | None = period_end.year if period_end else None
            if year is None:
                ym = _YEAR_RE.search(title)
                year = int(ym.group(1)) if ym else None
            if year is None:
                year = int(str(item.get("date", "0000"))[:4]) or None
            if not year:
                continue
            ftype = _filing_type(title_lower)
            filing = FinancialFiling(
                company_id=company_id,
                year=year,
                type=ftype,
                period_end=period_end,
                currency="KES",
                document_url=source_url,
                document_format="pdf",
                source_url=_ANNOUNCEMENTS_URL,
            )
            existing = best_by_year.get(year)
            if existing is None or (
                existing.type is not FilingType.ANNUAL_REPORT
                and ftype is FilingType.ANNUAL_REPORT
            ):
                best_by_year[year] = filing

        ordered = sorted(best_by_year.values(), key=lambda f: f.year, reverse=True)
        return ordered[: max(1, years)]

    def _match_from_event(self, event: dict) -> CompanyMatch:
        name = _clean_name(event.get("title", {}).get("rendered", ""))
        slug = event.get("slug", "")
        return CompanyMatch(
            id=slug,
            name=name,
            country="KE",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER, value=slug, label="NSE issuer"
                )
            ],
            status="Listed (Nairobi Securities Exchange)",
            source_url=event.get("link") or _ANNOUNCEMENTS_URL,
        )

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, *, params: dict
    ) -> list[dict]:
        resp = await get_with_retry(client, url, params=params)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
