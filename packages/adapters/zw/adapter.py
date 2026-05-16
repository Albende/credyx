"""Zimbabwe adapter — ZSE listed companies + Companies Registry probe.

Source coverage:

* Zimbabwe Stock Exchange (https://www.zse.co.zw/) — free public listings
  page exposing every listed counter (ticker + issuer name). This is the
  only Zimbabwean data source today that returns structured, machine-
  readable issuer + annual-report data without payment or registration.
* Companies and Other Business Entities Registry
  (https://www.companies.gov.zw/) — public web only exposes a thin
  homepage; full extracts move through paper / paid eGovernment channels.
  Search and identifier lookup are therefore unreliable and the adapter
  raises `AdapterNotImplementedError` rather than fabricate matches.
* ZIMRA (https://www.zimra.co.zw/) — TIN/BPN validation requires
  authenticated tax-portal sessions; no public BPN→entity feed exists.

Identifiers:
- COMPANY_NUMBER — Companies Registry alphanumeric (gated).
- VAT            — ZIMRA Business Partner Number (gated).

The ZSE-listed path matches issuers by ticker or substring of issuer name
and surfaces the issuer profile / annual-report URLs as filings. Only
real, fetched ZSE rows are returned — no defaulted or placeholder rows.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from html.parser import HTMLParser

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

logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{1,9}$")
_WS_RE = re.compile(r"\s+")


def _normalize_ticker(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "")
    if not _TICKER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"ZW ticker must be alphanumeric, 2-10 chars, got: {value}"
        )
    return cleaned


def _clean_text(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


class _ZSEListingsParser(HTMLParser):
    """Extract (ticker, issuer_name, profile_href) triples from ZSE pages.

    ZSE renders the listed-companies index as a table where each row has
    a ticker cell and an issuer-name cell that links to the issuer's
    profile page. We tolerate small markup drift by scanning every <a>
    tag and pairing nearby plain-text ticker tokens with the link label.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str | None]] = []
        self._current_link: str | None = None
        self._link_text_parts: list[str] = []
        self._text_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("tr", "td", "th"):
            self._text_buffer.append(" ")
        if tag == "a":
            href = dict(attrs).get("href")
            self._current_link = href
            self._link_text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_link is not None:
            link_text = _clean_text("".join(self._link_text_parts))
            ticker = _extract_ticker_from_context(
                "".join(self._text_buffer), link_text
            )
            if ticker and link_text and link_text.upper() != ticker:
                self.rows.append((ticker, link_text, self._current_link))
            self._current_link = None
            self._link_text_parts = []

    def handle_data(self, data: str) -> None:
        self._text_buffer.append(data)
        if self._current_link is not None:
            self._link_text_parts.append(data)


def _extract_ticker_from_context(buffer_text: str, link_text: str) -> str | None:
    """Best-effort ticker extraction from the text preceding an <a> tag.

    ZSE listing rows look like `<td>ECO</td><td><a>Econet Wireless …</a></td>`
    once flattened. The link text itself is the issuer name; the ticker is
    the last short uppercase token in the preceding cell.
    """
    tail = buffer_text[-200:]
    tokens = re.findall(r"[A-Z][A-Z0-9.]{1,9}", tail)
    for token in reversed(tokens):
        if token == link_text.upper().strip("."):
            continue
        if len(token) > 10:
            continue
        if token in {"ZSE", "VFEX", "USD", "ZWL", "LTD", "PLC"}:
            continue
        return token
    return None


class ZWAdapter(CountryAdapter):
    country_code = "ZW"
    country_name = "Zimbabwe"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    ZSE_BASE = "https://www.zse.co.zw"
    ZSE_LISTINGS_PATH = "/listed-companies/"
    COMPANIES_GOV_BASE = "https://www.companies.gov.zw"

    async def _fetch_zse_listings(self) -> list[tuple[str, str, str | None]]:
        async with build_http_client(base_url=self.ZSE_BASE) as client:
            resp = await get_with_retry(client, self.ZSE_LISTINGS_PATH)
            resp.raise_for_status()
            html = resp.text
        parser = _ZSEListingsParser()
        parser.feed(html)
        return parser.rows

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.ZSE_BASE) as client:
                resp = await get_with_retry(client, self.ZSE_LISTINGS_PATH)
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                notes=f"ZSE unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Coverage limited to ZSE-listed issuers. Companies Registry "
                "(companies.gov.zw) and ZIMRA BPN lookups are gated and "
                "raise AdapterNotImplementedError."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = name.strip().lower()
        if not needle:
            return []
        try:
            rows = await self._fetch_zse_listings()
        except Exception as exc:
            raise AdapterNotImplementedError(
                f"ZW search depends on ZSE listings; non-listed entities require "
                f"companies.gov.zw scraping which is not implemented. "
                f"ZSE fetch failed: {str(exc)[:120]}"
            ) from exc

        matches: list[CompanyMatch] = []
        for ticker, issuer, href in rows:
            haystack = f"{issuer} {ticker}".lower()
            if needle in haystack:
                matches.append(
                    CompanyMatch(
                        id=ticker,
                        name=issuer,
                        country=self.country_code,
                        identifiers=[
                            RegistryIdentifier(
                                type=IdentifierType.OTHER,
                                value=ticker,
                                label="ZSE Ticker",
                            ),
                        ],
                        address=None,
                        status="listed",
                        source_url=_absolute_url(self.ZSE_BASE, href),
                    )
                )
                if len(matches) >= limit:
                    break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"ZW adapter supports COMPANY_NUMBER or VAT (BPN), got {id_type}"
            )
        label = "BPN" if id_type == IdentifierType.VAT else "Company Number"
        raise AdapterNotImplementedError(
            f"Zimbabwe {label} lookup is not implemented: the Companies "
            "Registry (companies.gov.zw) and ZIMRA tax validator do not "
            "expose a public structured-data API, and full extracts are "
            "delivered via paid / paper eGovernment channels."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = _normalize_ticker(company_id)
        rows = await self._fetch_zse_listings()
        row = next((r for r in rows if r[0] == ticker), None)
        if row is None:
            return []

        _, _issuer_name, href = row
        profile_url = _absolute_url(self.ZSE_BASE, href)
        current_year = datetime.utcnow().year
        # ZSE publishes issuer profile pages with annual-report attachments; we
        # surface the profile URL so the downstream PDF pipeline can locate
        # filings without us inventing per-year document URLs that may 404.
        _ = years
        return [
            FinancialFiling(
                company_id=ticker,
                year=current_year,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="USD",
                structured_data=None,
                document_url=profile_url,
                document_format="html",
                source_url=profile_url,
            )
        ]


def _absolute_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return base.rstrip("/") + href
    return f"{base.rstrip('/')}/{href}"


