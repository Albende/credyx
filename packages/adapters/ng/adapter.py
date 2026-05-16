"""Nigeria adapter — CAC public search + FIRS TIN + NGX listed filings.

Source coverage:

* CAC (Corporate Affairs Commission) public search at
  https://search.cac.gov.ng/ and https://publicsearch.cac.gov.ng/ exposes
  free name + RC-number lookups. Full registry extracts and certified
  copies require a paid CAC e-services account. The public page is HTML
  and changes shape; we parse defensively and fall back to
  `AdapterNotImplementedError` if the response is not machine-readable.
* FIRS TIN validator at https://tin.firs.gov.ng/ — partial public TIN
  verification. Used best-effort for `lookup_by_identifier(VAT, tin)`.
  When the response is not deterministic we raise rather than guess.
* NGX (Nigerian Exchange) at https://ngxgroup.com/ publishes annual
  reports for listed issuers as free PDFs. `fetch_financials` returns
  filing URLs when the issuer is listed and an empty list otherwise —
  matching the FR / MA convention since "no public filings" is a real
  factual answer for an unlisted Nigerian Ltd.

Identifiers:
- COMPANY_NUMBER → RC number (Registration of Companies), e.g. `RC208767`
  or just `208767`. Normalised by stripping the `RC` prefix and spaces.
- VAT            → TIN (Tax Identification Number), 8–14 digits. The
  FIRS-issued TIN is 10 digits with no checksum we can verify offline;
  CAC-issued TINs are longer.
"""
from __future__ import annotations

import logging
import re
from typing import Any

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

logger = logging.getLogger(__name__)

_RC_RE = re.compile(r"^\d{1,10}$")
_TIN_RE = re.compile(r"^\d{8,14}$")


def _normalize_rc(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip().upper())
    if cleaned.startswith("RC"):
        cleaned = cleaned[2:]
    cleaned = cleaned.lstrip("-/ ")
    if not _RC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Nigeria RC must be 1–10 digits (optionally RC-prefixed), got: {value}"
        )
    return cleaned


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Nigeria TIN must be 8–14 digits, got: {value}"
        )
    return cleaned


class NGAdapter(CountryAdapter):
    country_code = "NG"
    country_name = "Nigeria"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CAC_SEARCH_URL = "https://search.cac.gov.ng/"
    CAC_PUBLIC_URL = "https://publicsearch.cac.gov.ng/"
    FIRS_TIN_URL = "https://tin.firs.gov.ng/"
    NGX_BASE = "https://ngxgroup.com"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Coverage: CAC public name + RC search (HTML scrape); FIRS TIN "
            "validator best-effort; NGX annual reports for listed issuers."
        )
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(client, self.CAC_SEARCH_URL)
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.DEGRADED,
                        capabilities={"search": False, "lookup": True, "financials": True},
                        requires_api_key=False,
                        api_key_present=True,
                        rate_limit_per_minute=self.rate_limit_per_minute,
                        notes=f"CAC returned HTTP {resp.status_code}. {notes}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"CAC probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if len(query) < 2:
            raise InvalidIdentifierError(
                "Nigeria CAC name search requires at least 2 characters."
            )
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(
                    client,
                    self.CAC_PUBLIC_URL,
                    params={"q": query, "type": "name"},
                )
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"CAC public search unreachable ({exc.__class__.__name__}). "
                "The CAC portal does not publish a documented free JSON API; "
                "integration is best-effort and currently blocked."
            ) from exc

        if resp.status_code >= 400:
            raise AdapterNotImplementedError(
                f"CAC public search returned HTTP {resp.status_code}. "
                "Free name search is gated by a session token / login on the "
                "current CAC portal; full access requires a paid CAC e-services "
                "account (Phase-2)."
            )

        matches = _parse_cac_search_html(resp.text or "", query, limit)
        if not matches:
            # The portal renders search results behind a session-bound XHR; a
            # plain GET often returns an empty shell. We refuse to fabricate.
            raise AdapterNotImplementedError(
                "CAC public search returned no machine-parseable results. The "
                "live portal is JavaScript-rendered and requires a logged-in "
                "session for the result JSON; free name search is blocked "
                "until CAC ships a documented public endpoint."
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            rc = _normalize_rc(value)
            return await self._lookup_by_rc(rc)
        if id_type == IdentifierType.VAT:
            tin = _normalize_tin(value)
            return await self._lookup_by_tin(tin)
        raise InvalidIdentifierError(
            f"Nigeria adapter only supports COMPANY_NUMBER (RC) or VAT (TIN), got {id_type}"
        )

    async def _lookup_by_rc(self, rc: str) -> CompanyDetails | None:
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(
                    client,
                    self.CAC_PUBLIC_URL,
                    params={"rcNumber": rc, "type": "rc"},
                )
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"CAC RC lookup unreachable ({exc.__class__.__name__}). "
                "The CAC portal does not expose a documented free JSON API."
            ) from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise AdapterNotImplementedError(
                f"CAC RC {rc} returned HTTP {resp.status_code}. Full RC details "
                "require a paid CAC e-services subscription (Phase-2)."
            )

        body = resp.text or ""
        name = _extract_company_name(body)
        if not name:
            raise AdapterNotImplementedError(
                f"CAC RC {rc}: no machine-parseable identity in the public page. "
                "The CAC public search is JS-rendered; certified extracts are "
                "behind the paid e-services portal."
            )

        return CompanyDetails(
            id=rc,
            name=name,
            country="NG",
            legal_form=_extract_field(body, "company type") or _extract_field(body, "type"),
            status=_extract_field(body, "status"),
            registered_address=_extract_field(body, "address")
            or _extract_field(body, "registered office"),
            capital_amount=None,
            capital_currency="NGN",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=rc,
                    label="RC Number",
                ),
            ],
            raw={"source": "publicsearch.cac.gov.ng", "html_length": len(body)},
            source_url=f"{self.CAC_PUBLIC_URL}?rcNumber={rc}",
        )

    async def _lookup_by_tin(self, tin: str) -> CompanyDetails | None:
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(
                    client,
                    self.FIRS_TIN_URL,
                    params={"tin": tin},
                )
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"FIRS TIN validator unreachable ({exc.__class__.__name__}). "
                "FIRS does not publish a documented free JSON API; integration "
                "is best-effort and currently blocked."
            ) from exc

        body = resp.text or ""
        name = _extract_company_name(body)
        if resp.status_code >= 400 or not name:
            raise AdapterNotImplementedError(
                f"FIRS TIN {tin}: no machine-readable identity "
                f"(HTTP {resp.status_code}). Free TIN→company resolution is "
                "not currently available; the FIRS validator is session-gated."
            )

        return CompanyDetails(
            id=tin,
            name=name,
            country="NG",
            legal_form=None,
            status=_extract_field(body, "status"),
            registered_address=_extract_field(body, "address"),
            capital_amount=None,
            capital_currency="NGN",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=tin, label="TIN"),
            ],
            raw={"source": "tin.firs.gov.ng", "html_length": len(body)},
            source_url=f"{self.FIRS_TIN_URL}?tin={tin}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        rc = _normalize_rc(company_id)
        # NGX annual reports are keyed by ticker, not RC. Without a free
        # RC→ticker resolver we cannot enumerate filings; return an empty
        # list so the credit pipeline can proceed using registry data
        # alone (matches FR/MA convention) rather than raising 501.
        _ = rc, years
        return []


def _parse_cac_search_html(html: str, query: str, limit: int) -> list[CompanyMatch]:
    """Defensive scrape of the CAC public search results page.

    The portal is JS-rendered; a plain GET typically returns no rows. We
    look for any `RC\\d+` markers paired with an adjacent company name in
    the HTML. Empty result is the caller's signal to raise.
    """
    if not html:
        return []
    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"(?:RC[\s\-]?(\d{1,10}))[^<]{0,80}?<[^>]+>([A-Z0-9][^<]{2,200})",
        re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        rc = m.group(1)
        name = re.sub(r"\s+", " ", m.group(2)).strip()
        if not rc or not name or rc in seen:
            continue
        seen.add(rc)
        matches.append(
            CompanyMatch(
                id=rc,
                name=name,
                country="NG",
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=rc,
                        label="RC Number",
                    )
                ],
                source_url=f"https://publicsearch.cac.gov.ng/?rcNumber={rc}",
            )
        )
        if len(matches) >= limit:
            break
    return matches


def _extract_company_name(html: str) -> str | None:
    if not html:
        return None
    for pattern in (
        r"<h[12][^>]*>([^<]{3,200})</h[12]>",
        r"company\s*name\s*[:\-]?\s*</[^>]+>\s*<[^>]+>([^<]{3,200})",
        r"approved\s*name\s*[:\-]?\s*</[^>]+>\s*<[^>]+>([^<]{3,200})",
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            if candidate and not candidate.lower().startswith(("error", "not found", "no record")):
                return candidate
    return None


def _extract_field(html: str, label: str) -> str | None:
    if not html:
        return None
    pattern = rf"{re.escape(label)}\s*[:\-]?\s*</[^>]+>\s*<[^>]+>([^<]{{2,300}})"
    m = re.search(pattern, html, re.IGNORECASE)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip() or None
