"""Albania adapter — OpenCorporates.al (Albanian Institute of Science).

Source coverage:

* https://opencorporates.al/ — the free, no-auth open-data mirror of the
  Albanian commercial registry (QKB / QKR) published by the Albanian
  Institute of Science (AIS), the same civil-society group behind Open
  Data Albania and Open Procurement Albania. It exposes a per-company
  detail page keyed by NIPT and a name/NIPT search form. Crucially, each
  detail page also re-publishes the company's filed annual accounts:
  ``Annual Turnover`` and ``Profit before Tax`` per year, plus links to
  the actual filed financial-statement documents (``Pasqyra
  Financiare``) hosted on the same host. No authentication, no API key.

  This replaces the earlier qkb.gov.al HTML scrape, which exposed no
  financials in machine-readable form.

Identifier:
- VAT → NIPT. 10 characters in the canonical ``L\\d{8}L`` form
  (letter + 8 digits + letter, e.g. ``J61814094W``). The taxpayer ID
  doubles as VAT identifier; under the EU prefix convention this is
  rendered ``AL`` + NIPT.
- COMPANY_NUMBER → also the NIPT. Albania uses a single registry number
  across QKB and DPT, so we accept the same value under either label.

Financials:
- ``fetch_financials`` returns one ``FinancialFiling`` per reported year
  carrying the company's real published annual turnover and profit-
  before-tax figures (``structured_data``) and, where present, a
  ``document_url`` pointing at the actual filed statement document on
  opencorporates.al. Never fabricated: a year is only emitted when the
  source page carries a real figure or a real document link for it.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
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

logger = logging.getLogger(__name__)

# Canonical NIPT shape: leading letter + 8 digits + trailing letter.
_NIPT_RE = re.compile(r"^[A-Z]\d{8}[A-Z]$")

# ONE ALBANIA (ex Telekom Albania) — used as a liveness probe.
_HEALTH_PROBE_NIPT = "J61814094W"

_STATUS_ACTIVE_TOKENS = (
    "aktiv",
    "i regjistruar",
    "e regjistruar",
    "active",
    "registered",
)
_STATUS_INACTIVE_TOKENS = (
    "c'regjistruar",
    "ç'regjistruar",
    "çregjistruar",
    "cregjistruar",
    "shuar",
    "pezulluar",
    "i pezulluar",
    "falimentuar",
    "ne likuidim",
    "në likuidim",
    "deregistered",
    "dissolved",
    "liquidated",
    "suspended",
    "bankrupt",
    "inactive",
    "closed",
)

# Detail-page <th> labels (English UI). Values live in the sibling <td>.
_TH_TAX_ID = "tax registration number"
_TH_STATUS = "status"
_TH_LEGAL_FORM = "legal form"
_TH_FOUNDATION = "foundation year"
_TH_CAPITAL = "initial capital"
_TH_ADMIN = "administrators"
_TH_SCOPE = "scope"
_TH_ADDRESS = "address"
_TH_DISTRICT = "district"


def _normalize_nipt(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("AL") and _NIPT_RE.match(cleaned[2:]):
        cleaned = cleaned[2:]
    if not _NIPT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Albania NIPT must be letter+8 digits+letter (e.g. J61814094W), got: {value}"
        )
    return cleaned


def _parse_al_date(value: str | None) -> date | None:
    """opencorporates.al renders dates as DD/MM/YYYY; tolerate ISO/dots."""
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(token in low for token in _STATUS_INACTIVE_TOKENS):
        return "inactive"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _parse_amount(raw: str | None) -> float | None:
    """Albanian figures use space (or dot) thousands and ',' decimals.

    Examples: ``863 826 822,00`` → 863826822.0; ``-539 854 000,00`` →
    -539854000.0. A leading '-' is preserved as sign.
    """
    if not raw:
        return None
    s = raw.strip()
    negative = s.startswith("-")
    cleaned = re.sub(r"[^\d,]", "", s.replace(".", ""))
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", ".")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -val if negative else val


class ALAdapter(CountryAdapter):
    country_code = "AL"
    country_name = "Albania"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://opencorporates.al"
    SEARCH_PATH = "/sq/search/"
    DETAIL_PATH = "/en/nipt/"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en;q=0.9,sq;q=0.8",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, self.DETAIL_PATH + _HEALTH_PROBE_NIPT)
                resp.raise_for_status()
                page_text = _decode(resp).lower()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )

        alive = "opencorporates" in page_text or "nipt" in page_text
        financials_live = "annual turnover" in page_text or "profit before tax" in page_text
        if not alive:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="opencorporates.al responded but markup unrecognised.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": financials_live},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Registry + filed annual accounts live via opencorporates.al (AIS).",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with self._client() as client:
            resp = await get_with_retry(
                client, self.SEARCH_PATH, params={"name": query}
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            page_text = _decode(resp)

        matches: list[CompanyMatch] = []
        for card in _extract_search_cards(page_text):
            nipt = card["nipt"]
            matches.append(
                CompanyMatch(
                    id=nipt,
                    name=card["name"],
                    country=self.country_code,
                    identifiers=_identifiers(nipt),
                    address=card.get("address"),
                    status=_classify_status(card.get("status_raw")),
                    source_url=f"{self.BASE_URL}{self.DETAIL_PATH}{nipt}",
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                "Albania adapter only supports VAT (NIPT) or COMPANY_NUMBER "
                f"(also NIPT), got {id_type}"
            )
        nipt = _normalize_nipt(value)

        page_text = await self._fetch_detail(nipt)
        if page_text is None:
            return None
        record = _extract_company_record(page_text)
        if not record.get("name"):
            return None

        director_name = (record.get("director") or "").strip()
        return CompanyDetails(
            id=nipt,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_al_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=_parse_amount(record.get("capital")),
            capital_currency="ALL",
            identifiers=_identifiers(nipt),
            raw={
                "source": "opencorporates.al",
                "fields": record,
                "director_name": director_name or None,
                "business_object": record.get("business_object"),
                "district": record.get("district"),
            },
            source_url=f"{self.BASE_URL}{self.DETAIL_PATH}{nipt}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        nipt = _normalize_nipt(company_id)
        page_text = await self._fetch_detail(nipt)
        if page_text is None:
            return []

        turnover = _extract_year_series(page_text, r"Annual Turnover \(ALL")
        profit = _extract_year_series(page_text, r"Profit before Tax \(ALL")
        documents = _extract_document_links(page_text)

        reported_years = set(turnover) | set(profit) | set(documents)
        source_url = f"{self.BASE_URL}{self.DETAIL_PATH}{nipt}"

        filings: list[FinancialFiling] = []
        for year in sorted(reported_years, reverse=True):
            structured: dict[str, Any] = {}
            if year in turnover:
                structured["annual_turnover"] = turnover[year]
            if year in profit:
                structured["profit_before_tax"] = profit[year]
            doc_path = documents.get(year)
            document_url = f"{self.BASE_URL}{doc_path}" if doc_path else None
            document_format = _doc_format(doc_path) if doc_path else None
            filings.append(
                FinancialFiling(
                    company_id=nipt,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="ALL",
                    structured_data=structured or None,
                    document_url=document_url,
                    document_format=document_format,
                    source_url=source_url,
                )
            )
        return filings[:years]

    async def _fetch_detail(self, nipt: str) -> str | None:
        async with self._client() as client:
            resp = await get_with_retry(client, self.DETAIL_PATH + nipt)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return _decode(resp)


def _identifiers(nipt: str) -> list[RegistryIdentifier]:
    return [
        RegistryIdentifier(type=IdentifierType.VAT, value=nipt, label="NIPT"),
        RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=nipt, label="NIPT"),
    ]


def _decode(resp: httpx.Response) -> str:
    """opencorporates.al is predominantly UTF-8 with occasional stray
    Latin-1 accents in free-text fields; decode UTF-8 and replace the rare
    invalid byte rather than mangling every ``ë``/``ç`` via a Latin-1 pass."""
    body = resp.content
    if not body:
        return ""
    return body.decode("utf-8", errors="replace")


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return unescape(re.sub(r"\s+", " ", text)).strip()


_TH_TD_RE = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S | re.I)


def _extract_company_record(html: str) -> dict[str, Any]:
    if not html:
        return {}
    record: dict[str, Any] = {}

    m = re.search(
        r'<h2 class="title-divider">\s*<span>(.*?)</span>', html, re.S | re.I
    )
    if m:
        record["name"] = _clean(m.group(1))

    for label_html, value_html in _TH_TD_RE.findall(html):
        label = _clean(label_html).lower().rstrip(":")
        value = _clean(value_html)
        if not value:
            continue
        if label == _TH_TAX_ID:
            up = value.upper().replace(" ", "")
            if _NIPT_RE.match(up):
                record["nipt"] = up
        elif label == _TH_STATUS:
            record.setdefault("status_raw", value)
        elif label == _TH_LEGAL_FORM:
            record.setdefault("legal_form", value)
        elif label == _TH_FOUNDATION:
            record.setdefault("registration_date", value)
        elif label == _TH_CAPITAL:
            record.setdefault("capital", value)
        elif label == _TH_ADMIN:
            record.setdefault("director", value)
        elif label == _TH_SCOPE:
            record.setdefault("business_object", value)
        elif label == _TH_DISTRICT:
            record.setdefault("district", value)
        elif label == _TH_ADDRESS:
            record.setdefault("address", value)
    return record


_CARD_RE = re.compile(
    r'<h4 class="mb-0">(?P<name>.*?)</h4>(?P<body>.*?)'
    r'(?=<h4 class="mb-0">|<div id="footer"|\Z)',
    re.S | re.I,
)
_NIPT_LINK_RE = re.compile(r"/(?:en|sq)/nipt/([A-Za-z0-9]+)", re.I)
_MARKER_RE = re.compile(r'fa-map-marker"></i>\s*(.*?)</span>', re.S | re.I)


def _extract_search_cards(html: str) -> list[dict[str, Any]]:
    if not html:
        return []
    cards: list[dict[str, Any]] = []
    for m in _CARD_RE.finditer(html):
        body = m.group("body")
        link = _NIPT_LINK_RE.search(body)
        if not link:
            continue
        name = _clean(m.group("name"))
        if not name:
            continue
        addr_m = _MARKER_RE.search(body)
        address = _clean(addr_m.group(1)) if addr_m else None
        status_raw: str | None = None
        for token in _STATUS_INACTIVE_TOKENS + _STATUS_ACTIVE_TOKENS:
            if token in body.lower():
                status_raw = token
                break
        cards.append(
            {
                "name": name,
                "nipt": link.group(1).upper(),
                "address": address or None,
                "status_raw": status_raw,
            }
        )
    return cards


def _extract_year_series(html: str, label_prefix: str) -> dict[int, float]:
    """Pull ``<label> YYYY: <amount>`` pairs from a detail page section."""
    pattern = re.compile(
        label_prefix + r"[^)]*\)\s*(\d{4})\s*:\s*(-?[\d  .,]+)",
        re.I,
    )
    series: dict[int, float] = {}
    for year_str, raw in pattern.findall(html):
        amount = _parse_amount(raw)
        if amount is None:
            continue
        year = int(year_str)
        if 1990 <= year <= datetime.utcnow().year and year not in series:
            series[year] = amount
    return series


_DOC_RE = re.compile(
    r'href="(/documents/bilanci/[^"]+)"[^>]*>\s*([^<]*?(\d{4}))', re.I
)


def _extract_document_links(html: str) -> dict[int, str]:
    """Map a reporting year to the first filed-statement document for it."""
    docs: dict[int, str] = {}
    for href, _text, year_str in _DOC_RE.findall(html):
        # A stray Latin-1 byte in the filename decodes to U+FFFD; that URL
        # 404s, so never surface it as a downloadable document.
        if "�" in href:
            continue
        year = int(year_str)
        if 1990 <= year <= datetime.utcnow().year and year not in docs:
            docs[year] = href
    return docs


def _doc_format(path: str) -> str | None:
    low = path.lower()
    if ".pdf" in low:
        return "pdf"
    if ".xlsx" in low:
        return "xlsx"
    if ".xls" in low:
        return "xls"
    if ".doc" in low:
        return "doc"
    return None
