"""Malaysia adapter — Bursa Malaysia (listed issuers) + SSM e-Info (paid, excluded).

The Companies Commission of Malaysia (SSM / Suruhanjaya Syarikat Malaysia)
runs the only authoritative corporate register, but every programmatic and
human-readable lookup on https://www.ssm-einfo.my/ is paid (per-document
charges starting at RM10) and gated behind login + reCAPTCHA. There is no
free public name-search or per-company lookup endpoint, so this adapter:

* `search_by_name` and `lookup_by_identifier` raise
  ``AdapterNotImplementedError`` — per the project spec we never invent
  registry data and never silently swallow gaps with mocks.
* `fetch_financials` routes to **Bursa Malaysia** (the local stock
  exchange). Bursa publishes free annual reports for every listed issuer
  via its public JSON-ish endpoint at
  ``https://www.bursamalaysia.com/api/v1/announcements``. For unlisted
  Malaysian companies — the vast majority — we return ``[]`` rather than
  fabricating filings.

Identifier formats accepted (both map to ``IdentifierType.COMPANY_NUMBER``):

* **New format** — 12 digits, e.g. ``197001000465`` (introduced Jan 2019).
* **Old format** — up to 7 digits + a single check letter, e.g.
  ``20076-K`` / ``6463-H``. Normalised to ``DIGITS-LETTER`` uppercase.

A caller can also encode the Bursa stock code directly via
``BURSA:<code>`` (e.g. ``BURSA:5347`` for Petronas Gas) so
``fetch_financials`` can skip the SSM-side resolution it cannot perform.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
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

_NEW_REG_RE = re.compile(r"^\d{12}$")
_OLD_REG_RE = re.compile(r"^\d{1,7}-[A-Z]$")
_BURSA_RE = re.compile(r"^\d{4,5}$")
_PACKED_BURSA_RE = re.compile(r"^BURSA[:/](?P<code>\d{4,5})$", re.IGNORECASE)


def _normalize_company_number(value: str) -> str:
    """Normalise to either ``NNNNNNNNNNNN`` (12 digits) or ``NNNNNNN-L``.

    Accepts the historical hyphenless old form (``20076K``), mixed case
    check letters, and a leading ``MY`` country prefix. Never invents
    a check letter when one is missing.
    """
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned.startswith("MY"):
        cleaned = cleaned[2:]
    if cleaned.startswith("CR:"):
        cleaned = cleaned[3:]

    if _NEW_REG_RE.match(cleaned):
        return cleaned

    if "-" not in cleaned:
        # Old format hyphen is canonical (SSM prints it on every extract);
        # accept the bare form only when the trailing char is a letter so
        # we never reconstruct ambiguous inputs.
        m = re.match(r"^(\d{1,7})([A-Z])$", cleaned)
        if m:
            cleaned = f"{m.group(1)}-{m.group(2)}"

    if _OLD_REG_RE.match(cleaned):
        digits, _, letter = cleaned.partition("-")
        return f"{digits}-{letter}"

    raise InvalidIdentifierError(
        "Malaysia company number must be either the 12-digit new-format "
        f"registration number or the legacy DIGITS-LETTER form, got: {value}"
    )


def _split_packed_id(value: str) -> tuple[str | None, str | None]:
    """Return (company_number, bursa_stock_code) from a caller-supplied id."""
    raw = value.strip().replace(" ", "")
    m = _PACKED_BURSA_RE.match(raw)
    if m:
        return None, m.group("code").zfill(4)
    try:
        return _normalize_company_number(raw), None
    except InvalidIdentifierError:
        return None, None


def _parse_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        # Bursa serves human-formatted dates like "31 Dec 2023" on some feeds.
        m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$", s)
        if m:
            month_map = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            mon = month_map.get(m.group(2)[:3].lower())
            if mon:
                try:
                    return date(int(m.group(3)), mon, int(m.group(1)))
                except ValueError:
                    return None
        return None


class MYAdapter(CountryAdapter):
    country_code = "MY"
    country_name = "Malaysia"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BURSA_BASE = "https://www.bursamalaysia.com"
    BURSA_API = "https://www.bursamalaysia.com/api/v1"
    SSM_EINFO_URL = "https://www.ssm-einfo.my/"

    _SSM_BLOCKED_NOTE = (
        "SSM e-Info (https://www.ssm-einfo.my/) is the only authoritative "
        "Malaysian corporate registry and every full-record extract is paid "
        "(per-document fee) and gated by login + reCAPTCHA. No free public "
        "name-search or identifier-lookup endpoint exists, so this adapter "
        "refuses to fabricate results. Pass a Bursa-listed company via "
        "fetch_financials('BURSA:<stockCode>') for the listed-issuer path."
    )

    def _bursa_headers(self) -> dict[str, str]:
        # Bursa's JSON endpoints 403 anonymous requests that omit a browser-
        # style Accept header / referer.
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en;q=0.9, ms;q=0.8",
            "Referer": f"{self.BURSA_BASE}/",
            "Origin": self.BURSA_BASE,
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.BURSA_BASE,
                headers=self._bursa_headers(),
                timeout=15.0,
            ) as client:
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
                        notes=f"Bursa Malaysia HTTP {resp.status_code}",
                    )
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
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            requires_api_key=False,
            api_key_present=False,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry (SSM e-Info) is paid-only and blocked; "
                "fetch_financials best-effort via Bursa Malaysia for "
                "listed issuers. Unlisted companies return []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(self._SSM_BLOCKED_NOTE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Malaysia only supports COMPANY_NUMBER, got {id_type}"
            )
        # Validate format up-front so callers get an InvalidIdentifierError
        # for clearly malformed input rather than the generic "not implemented".
        _normalize_company_number(value)
        raise AdapterNotImplementedError(self._SSM_BLOCKED_NOTE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        company_number, bursa_code = _split_packed_id(company_id)
        if bursa_code is None and company_number is None:
            raise InvalidIdentifierError(
                "Malaysia fetch_financials expects either a registration "
                f"number or 'BURSA:<stockCode>', got: {company_id}"
            )
        if bursa_code is None:
            # Without a Bursa code we cannot resolve listed-issuer filings
            # (the SSM → Bursa mapping itself is paid). Unlisted = no free
            # financial source → return [] per spec.
            return []

        return await self._fetch_bursa_annual_reports(
            stock_code=bursa_code,
            company_id=company_number or f"BURSA:{bursa_code}",
            years=years,
        )

    async def _fetch_bursa_annual_reports(
        self, *, stock_code: str, company_id: str, years: int
    ) -> list[FinancialFiling]:
        cutoff_year = datetime.utcnow().year - years
        filings: list[FinancialFiling] = []
        try:
            async with build_http_client(
                base_url=self.BURSA_API,
                headers=self._bursa_headers(),
                timeout=20.0,
            ) as client:
                resp = await get_with_retry(
                    client,
                    "/announcements",
                    params={
                        "stock_code": stock_code,
                        "type": "annual-report",
                        "per_page": 50,
                    },
                )
                if resp.status_code in (401, 403, 404):
                    return []
                resp.raise_for_status()
                try:
                    payload = resp.json()
                except ValueError:
                    return []
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.debug("Bursa fetch failed for %s: %s", stock_code, exc)
            return []

        rows = _extract_bursa_rows(payload)
        for row in rows:
            period_end = _parse_iso_date(
                row.get("period_end")
                or row.get("financial_year_end")
                or row.get("date")
                or row.get("announcement_date")
            )
            year = _coerce_int(
                row.get("year") or row.get("financial_year")
            )
            if year is None and period_end is not None:
                year = period_end.year
            if year is None:
                continue
            if year < cutoff_year:
                continue

            doc_url = row.get("document_url") or row.get("url") or row.get("attachment_url")
            filings.append(
                FinancialFiling(
                    company_id=company_id,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end or date(year, 12, 31),
                    currency="MYR",
                    document_url=doc_url,
                    document_format=(
                        "pdf" if isinstance(doc_url, str) and doc_url.lower().endswith(".pdf")
                        else "html"
                    ),
                    source_url=(
                        f"{self.BURSA_BASE}/market_information/announcements/"
                        f"company_announcement?stock_code={stock_code}"
                    ),
                )
            )
        filings.sort(key=lambda f: f.period_end or date.min, reverse=True)
        return filings


def _extract_bursa_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "announcements", "records"):
        v = payload.get(key)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)]
        if isinstance(v, dict):
            for inner_key in ("items", "data", "rows"):
                inner = v.get(inner_key)
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
    return []


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
