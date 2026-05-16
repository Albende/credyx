"""South Africa adapter — CIPC BizPortal + JSE.

Free public sources only.

- **Registry** — Companies and Intellectual Property Commission (CIPC).
  CIPC's full eServices portal (https://eservices.cipc.co.za/) charges for
  every company extract and requires an authenticated customer account, so
  it is out of scope per the no-paid-API rule. The free public face is
  **BizPortal** (https://www.bizportal.gov.za/), a Department of Small
  Business Development service that exposes name + registration-number
  lookups against the live CIPC database. The HTML form is brittle and
  occasionally rate-limited, so this adapter scrapes defensively: parsing
  failures or hard blocks degrade to a meaningful 501 rather than fabricated
  data.

- **Financials** — Annual financial statements are filed with CIPC but only
  released through paid eServices. For JSE-listed issuers the
  Johannesburg Stock Exchange publishes annual reports for free at
  https://www.jse.co.za/listed-companies (SENS announcements + investor
  relations). Mapping a CIPC registration number to a JSE share code is not
  available through any free API, so we surface the JSE listed-companies
  search URL as a `source_url` hint and return `[]` for non-listed entities
  rather than guess.

Identifiers
- `COMPANY_NUMBER` — CIPC registration number in the canonical format
  `YYYY/NNNNNN/NN` (year of incorporation, sequence, entity-type suffix
  e.g. `/06` for Pty Ltd, `/07` for public company, `/08` for NPC).
- `VAT` — 10-digit SARS VAT number; first digit is always `4`. SARS does
  not expose a free VAT validation API so we only normalize and surface;
  we do not claim to verify.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    BlockedByRegistryError,
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

_REG_RE = re.compile(r"^(\d{4})[\s/\-]?(\d{4,7})[\s/\-]?(\d{2})$")
_VAT_RE = re.compile(r"^4\d{9}$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "request blocked",
    "cloudflare",
    "are you human",
)


def _normalize_company_number(value: str) -> str:
    """Parse the CIPC YYYY/NNNNNN/NN format, tolerating spaces / dashes."""
    cleaned = value.strip().upper().replace(" ", "")
    match = _REG_RE.match(cleaned)
    if not match:
        raise InvalidIdentifierError(
            f"ZA registration number must be YYYY/NNNNNN/NN: {value}"
        )
    year, seq, suffix = match.groups()
    # CIPC pads the sequence component to 7 digits when written canonically.
    return f"{year}/{seq.zfill(7)}/{suffix}"


def _normalize_vat(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip())
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"ZA VAT number must be 10 digits starting with 4: {value}"
        )
    return cleaned


def _strip_html(html: str) -> str:
    """Collapse tags + whitespace from an HTML fragment for cheap parsing."""
    text = _TAG_RE.sub(" ", html)
    return _WS_RE.sub(" ", text).strip()


def _looks_blocked(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


class ZAAdapter(CountryAdapter):
    country_code = "ZA"
    country_name = "South Africa"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    BIZPORTAL_BASE = "https://www.bizportal.gov.za"
    JSE_LISTED_URL = "https://www.jse.co.za/listed-companies"

    def __init__(self) -> None:
        # Most parsing logic is overridable via env so we can chase
        # BizPortal markup changes without redeploys.
        self._search_path = os.getenv(
            "ZA_BIZPORTAL_SEARCH_PATH", "/company-search"
        )

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BIZPORTAL_BASE,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, "/")
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": False,
                        },
                        rate_limit_per_minute=self.rate_limit_per_minute,
                        notes=f"BizPortal returned HTTP {resp.status_code}.",
                    )
                if _looks_blocked(resp.text):
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.BLOCKED,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": False,
                        },
                        rate_limit_per_minute=self.rate_limit_per_minute,
                        notes="BizPortal served a CAPTCHA / WAF challenge.",
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
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "BizPortal HTML scrape: search + reg-number lookup only. "
                "Financials require paid CIPC eServices or JSE manual lookup."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not name or not name.strip():
            return []
        params = {"q": name.strip()}
        async with self._client() as client:
            try:
                resp = await get_with_retry(
                    client, self._search_path, params=params
                )
            except httpx.HTTPError as exc:
                raise AdapterError(f"BizPortal request failed: {exc}") from exc

            if resp.status_code == 404:
                raise AdapterNotImplementedError(
                    "BizPortal search endpoint moved; update ZA_BIZPORTAL_SEARCH_PATH."
                )
            if resp.status_code >= 500:
                raise AdapterError(
                    f"BizPortal returned HTTP {resp.status_code} for name search."
                )
            body = resp.text
            if _looks_blocked(body):
                raise BlockedByRegistryError(
                    "BizPortal blocked the search request (CAPTCHA / WAF)."
                )

        matches = _parse_search_results(body, limit=limit)
        if not matches:
            # BizPortal's public HTML does not currently expose stable result
            # selectors. Surface a clear 501 rather than silently returning
            # nothing — per the spec, an empty list must mean "no matches",
            # not "we couldn't parse the page".
            if _looks_like_search_page(body):
                return []
            raise AdapterNotImplementedError(
                "BizPortal search results layout not recognized; "
                "manual review at https://www.bizportal.gov.za/ required."
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            reg = _normalize_company_number(value)
        elif id_type == IdentifierType.VAT:
            # SARS does not publish a free VAT lookup; we cannot resolve VAT
            # to a registration record without a paid provider.
            vat = _normalize_vat(value)
            raise AdapterNotImplementedError(
                f"ZA VAT lookup not available without paid SARS access (got {vat})."
            )
        else:
            raise InvalidIdentifierError(
                f"ZA supports COMPANY_NUMBER or VAT, got {id_type}"
            )

        encoded = quote_plus(reg)
        async with self._client() as client:
            try:
                resp = await get_with_retry(
                    client,
                    self._search_path,
                    params={"q": reg, "registration": reg},
                )
            except httpx.HTTPError as exc:
                raise AdapterError(f"BizPortal lookup failed: {exc}") from exc

            if resp.status_code == 404:
                return None
            if resp.status_code >= 500:
                raise AdapterError(
                    f"BizPortal returned HTTP {resp.status_code} for lookup."
                )
            body = resp.text
            if _looks_blocked(body):
                raise BlockedByRegistryError(
                    "BizPortal blocked the lookup request (CAPTCHA / WAF)."
                )

        details = _parse_company_detail(body, reg)
        if details is None:
            if _looks_like_search_page(body):
                # Confirmed BizPortal response but no matching record.
                return None
            raise AdapterNotImplementedError(
                "BizPortal detail layout not recognized; "
                f"manual review at https://www.bizportal.gov.za/?q={encoded} required."
            )
        return details

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Free path: only JSE-listed issuers publish annual reports on the
        # open web, and there is no free CIPC→JSE share-code mapping. We
        # return [] rather than fabricate a synthetic filing list.
        try:
            _normalize_company_number(company_id)
        except InvalidIdentifierError:
            # Allow callers to pass JSE share codes etc. without crashing.
            logger.debug("Non-CIPC company_id passed to ZA fetch_financials: %s", company_id)
        return []


def _looks_like_search_page(body: str) -> bool:
    text = body.lower()
    return "bizportal" in text and (
        "search" in text or "company" in text or "registration" in text
    )


def _parse_search_results(html: str, *, limit: int) -> list[CompanyMatch]:
    """Best-effort BizPortal search result extraction.

    BizPortal renders results inside table rows; markup has changed several
    times. We scan for `YYYY/NNNNNN/NN` reg-number occurrences and pair each
    with the closest preceding non-empty text node as the company name.
    """
    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    text_chunks = _split_text_chunks(html)
    pending_name: str | None = None
    for chunk in text_chunks:
        candidate = chunk.strip()
        if not candidate:
            continue
        reg_match = _REG_RE.match(candidate.replace(" ", ""))
        if reg_match:
            reg = _normalize_company_number(candidate)
            if reg in seen:
                continue
            seen.add(reg)
            name = pending_name or "(name not parsed)"
            matches.append(
                CompanyMatch(
                    id=reg,
                    name=name,
                    country="ZA",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=reg,
                            label="CIPC Registration Number",
                        )
                    ],
                    source_url=f"https://www.bizportal.gov.za/?q={quote_plus(reg)}",
                )
            )
            pending_name = None
            if len(matches) >= limit:
                break
        else:
            # Treat anything that looks like a company-style name as a candidate.
            if len(candidate) <= 200 and not candidate.startswith(("http", "{")):
                pending_name = candidate
    return matches


def _split_text_chunks(html: str) -> list[str]:
    # Replace common block delimiters with newlines so consecutive cells are
    # not concatenated.
    cleaned = re.sub(
        r"</(td|tr|li|p|div|h\d|span)>", "\n", html, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = _TAG_RE.sub(" ", cleaned)
    return [_WS_RE.sub(" ", line).strip() for line in cleaned.splitlines()]


def _parse_company_detail(html: str, reg: str) -> CompanyDetails | None:
    if reg.replace(" ", "") not in html.replace(" ", ""):
        return None
    chunks = _split_text_chunks(html)
    name: str | None = None
    status: str | None = None
    legal_form: str | None = None
    address: str | None = None
    for i, chunk in enumerate(chunks):
        lower = chunk.lower()
        if not name and chunk and reg not in chunk and len(chunk) <= 200:
            # First substantial non-label, non-registration text is the name.
            if not any(
                kw in lower
                for kw in ("registration", "status", "type", "address", "search")
            ):
                name = chunk
        if "status" in lower and i + 1 < len(chunks):
            status = chunks[i + 1] or status
        if "enterprise type" in lower or "company type" in lower:
            if i + 1 < len(chunks):
                legal_form = chunks[i + 1] or legal_form
        if "address" in lower and i + 1 < len(chunks):
            candidate = chunks[i + 1]
            if candidate and candidate.lower() != "address":
                address = candidate

    if not name:
        return None

    return CompanyDetails(
        id=reg,
        name=name,
        country="ZA",
        legal_form=legal_form,
        status=status,
        registered_address=address,
        capital_currency="ZAR",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=reg,
                label="CIPC Registration Number",
            )
        ],
        raw={"bizportal_text": " | ".join(chunks)[:8000]},
        source_url=f"https://www.bizportal.gov.za/?q={quote_plus(reg)}",
        fetched_at=datetime.utcnow(),
    )
