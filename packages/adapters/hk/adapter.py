"""Hong Kong adapter — HKEXnews (listed issuers) + optional OpenCorporates.

Free public sources only, per the project's no-paid-API rule.

- **Primary (key-free) — HKEXnews.** The Hong Kong Companies Registry
  (ICRIS / e-Services) is a CSRF/SPA front-end whose full extracts sit
  behind a HK$8/doc paywall, so it is not usable programmatically for
  free. HKEXnews (https://www1.hkexnews.hk), the Stock Exchange's public
  disclosure portal, exposes two undocumented-but-stable JSON endpoints
  that need no key:
    - ``/search/prefix.do`` — autocomplete: name/stock-code -> the
      issuer's internal ``stockId``, 5-digit ``code`` and short ``name``.
      Powers ``search_by_name`` and ``lookup_by_identifier``.
    - ``/search/titleSearchServlet.do`` — per-issuer filing list with the
      real PDF ``FILE_LINK``. Filtered to ``Annual Report`` this yields the
      actual filed annual reports. Powers ``fetch_financials``.
  Coverage is therefore HK **listed issuers** (SEHK main board). For a
  listed issuer the free identifier is its HKEX **stock code**
  (5-digit, zero-padded, e.g. ``00700`` = Tencent).

- **Optional (key-gated) — OpenCorporates HK mirror.** When
  ``OPENCORPORATES_API_KEY`` is present we additionally accept the ICRIS
  **CR number** in ``lookup_by_identifier`` and use it to resolve a stock
  code for ``fetch_financials``. Absent the key we neither reach ICRIS nor
  fabricate CR data — CR lookups return ``None`` / raise.

Identifiers
- ``COMPANY_NUMBER`` — HKEX stock code (5-digit, key-free) for listed
  issuers; or a 7-digit ICRIS CR number when an OpenCorporates key is set.
- ``OTHER`` — 8-digit BR (Business Registration) number. IRD's BR Number
  Enquiry is paid; accepted for normalization only, never looked up.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.adapters._global.opencorporates import OpenCorporatesClient
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

_CR_RE = re.compile(r"^\d{1,7}$")
_BR_RE = re.compile(r"^\d{8}$")
_STOCK_RE = re.compile(r"^\d{1,5}$")
_YEAR_RE = re.compile(r"(19|20)\d{2}")

# CR/stock codes can be packed via "CR:1234567", "HKEX:00700",
# "1234567/HKEX:00700" or "0700@hk" — accepted by fetch_financials so a
# caller can pre-resolve the listing without a second round-trip.
_PACKED_RE = re.compile(
    r"^(?:CR[:/])?(?P<cr>\d{1,7})?"
    r"(?:[/@]HKEX[:/]?(?P<hkex>\d{1,5}))?$",
    re.IGNORECASE,
)


def _normalize_cr_number(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.upper().startswith("CR"):
        cleaned = cleaned[2:].lstrip(":/")
    if not _CR_RE.match(cleaned):
        raise InvalidIdentifierError(f"HK CR number must be up to 7 digits: {value}")
    return cleaned.zfill(7)


def _normalize_br_number(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _BR_RE.match(cleaned):
        raise InvalidIdentifierError(f"HK BR number must be 8 digits: {value}")
    return cleaned


def _try_stock_code(value: str) -> str | None:
    """Return a 5-digit zero-padded HKEX stock code, or None if not code-shaped."""
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.upper().startswith("HKEX"):
        cleaned = cleaned[4:].lstrip(":/")
    if _STOCK_RE.match(cleaned):
        return cleaned.zfill(5)
    return None


def _split_packed_id(value: str) -> tuple[str | None, str | None]:
    """Return (cr_number, stock_code) parsed from a caller-supplied id."""
    raw = value.strip().replace(" ", "")
    m = _PACKED_RE.match(raw)
    if not m:
        return None, None
    cr = m.group("cr")
    hkex = m.group("hkex")
    return (cr.zfill(7) if cr else None, hkex.zfill(5) if hkex else None)


class HKAdapter(CountryAdapter):
    country_code = "HK"
    country_name = "Hong Kong"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.OTHER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    HKEX_BASE = "https://www1.hkexnews.hk"
    ICRIS_BASE = "https://www.icris.cr.gov.hk/csci/"

    def __init__(self, opencorporates_api_key: str | None = None) -> None:
        self.oc_key = opencorporates_api_key or os.getenv("OPENCORPORATES_API_KEY")
        self._oc = OpenCorporatesClient(api_key=self.oc_key) if self.oc_key else None

    def _titlesearch_url(self, code: str) -> str:
        return (
            f"{self.HKEX_BASE}/search/titlesearch.xhtml"
            f"?lang=EN&category=0&market=SEHK&searchType=1&t2Gp=-2&t2Code=-2"
            f"&stockId=&stockCode={code}"
        )

    async def _prefix_search(self, query: str) -> list[dict[str, Any]]:
        """Query HKEXnews autocomplete; returns [{stockId, code, name}, ...]."""
        async with build_http_client(base_url=self.HKEX_BASE, timeout=20.0) as client:
            resp = await get_with_retry(
                client,
                "/search/prefix.do",
                params={
                    "callback": "c",
                    "lang": "EN",
                    "type": "A",
                    "name": query,
                    "market": "SEHK",
                },
                headers={"Referer": f"{self.HKEX_BASE}/search/titlesearch.xhtml"},
            )
            resp.raise_for_status()
            body = resp.text.strip()
            m = re.search(r"\((.*)\)\s*;?\s*$", body, re.DOTALL)
            if not m:
                return []
            payload = json.loads(m.group(1))
        rows = payload.get("stockInfo") or []
        out: list[dict[str, Any]] = []
        for r in rows:
            code = str(r.get("code") or "").strip()
            if not _STOCK_RE.match(code.lstrip("0") or "0"):
                continue
            out.append(
                {
                    "stockId": r.get("stockId"),
                    "code": code.zfill(5),
                    "name": (r.get("name") or "").strip(),
                }
            )
        return out

    async def _resolve_stock(self, code: str) -> dict[str, Any] | None:
        """Resolve a 5-digit stock code to its {stockId, code, name} row."""
        for row in await self._prefix_search(code):
            if row["code"] == code:
                return row
        return None

    async def _annual_reports(
        self, stock_id: Any, code: str, years: int
    ) -> list[FinancialFiling]:
        current_year = datetime.utcnow().year
        from_date = f"{current_year - max(years, 1) - 1}0101"
        to_date = datetime.utcnow().strftime("%Y%m%d")
        async with build_http_client(base_url=self.HKEX_BASE, timeout=30.0) as client:
            resp = await get_with_retry(
                client,
                "/search/titleSearchServlet.do",
                params={
                    "sortDir": "0",
                    "sortByOptions": "DateTime",
                    "category": "0",
                    "market": "SEHK",
                    "stockId": stock_id,
                    "documentType": "-1",
                    "fromDate": from_date,
                    "toDate": to_date,
                    "title": "Annual Report",
                    "searchType": "1",
                    "t": str(int(time.time() * 1000)),
                    "lang": "EN",
                },
                headers={"Referer": f"{self.HKEX_BASE}/search/titlesearch.xhtml"},
            )
            resp.raise_for_status()
            rows = json.loads(resp.json().get("result") or "[]")

        seen_years: set[int] = set()
        filings: list[FinancialFiling] = []
        for row in rows:
            title = (row.get("TITLE") or "").strip()
            link = (row.get("FILE_LINK") or "").strip()
            if "annual report" not in title.lower() or not link:
                continue
            year = _report_year(title, row.get("DATE_TIME"))
            if year is None or year in seen_years:
                continue
            seen_years.add(year)
            filings.append(
                FinancialFiling(
                    company_id=code,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=None,
                    currency=None,
                    document_url=f"{self.HKEX_BASE}{link}",
                    document_format="pdf",
                    source_url=self._titlesearch_url(code),
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings[:years]

    async def health_check(self) -> AdapterHealth:
        try:
            rows = await self._prefix_search("00700")
            reachable = any(r["code"] == "00700" for r in rows)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        status = AdapterStatus.OK if reachable else AdapterStatus.DEGRADED
        notes = (
            "HKEXnews reachable — search/lookup/financials for HK listed "
            "issuers (SEHK) key-free. "
            + ("OpenCorporates key present: CR-number lookups enabled."
               if self._oc else
               "Set OPENCORPORATES_API_KEY to also resolve ICRIS CR numbers.")
        )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=bool(self._oc),
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._prefix_search(name)
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            code = row["code"]
            matches.append(
                CompanyMatch(
                    id=code,
                    name=row["name"],
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=code,
                            label="HKEX Stock Code",
                        )
                    ],
                    status="listed",
                    source_url=self._titlesearch_url(code),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.OTHER:
            _normalize_br_number(value)
            raise AdapterNotImplementedError(
                "HK BR (Business Registration) lookup needs the paid IRD BR "
                "Number Enquiry. Pass the HKEX stock code (or a CR number "
                "with OPENCORPORATES_API_KEY set) instead."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"HK supports COMPANY_NUMBER and OTHER, got {id_type}"
            )

        code = _try_stock_code(value)
        if code is not None:
            row = await self._resolve_stock(code)
            if row is not None:
                return _details_from_hkex(row, self._titlesearch_url(code))

        if self._oc is not None:
            cr = _normalize_cr_number(value)
            company = await self._oc.get_company("hk", cr)
            if company is None:
                return None
            return _details_from_oc(company, cr)

        if code is not None:
            return None
        raise AdapterNotImplementedError(
            "HK CR-number lookup requires OPENCORPORATES_API_KEY (ICRIS blocks "
            "programmatic clients). Pass an HKEX stock code for key-free lookup."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cr, packed_code = _split_packed_id(company_id)
        code = packed_code or _try_stock_code(company_id)
        if code is None and cr is not None and self._oc is not None:
            code = await self._resolve_hkex_code(cr)
        if code is None:
            return []

        row = await self._resolve_stock(code)
        if row is None:
            return []
        return await self._annual_reports(row["stockId"], code, years)

    async def _resolve_hkex_code(self, cr: str) -> str | None:
        if self._oc is None:
            return None
        company = await self._oc.get_company("hk", cr)
        if not company:
            return None
        for ident in company.get("identifiers", []) or []:
            scheme = (ident.get("identifier_system_code") or "").lower()
            if "hkex" in scheme or "stock_exchange_of_hong_kong" in scheme:
                raw = str(ident.get("uid") or "").strip()
                if _STOCK_RE.match(raw):
                    return raw.zfill(5)
        return None


def _report_year(title: str, date_time: str | None) -> int | None:
    m = _YEAR_RE.search(title)
    if m:
        return int(m.group(0))
    if date_time:
        dm = re.search(r"/(\d{4})\b", date_time)
        if dm:
            return int(dm.group(1)) - 1
    return None


def _details_from_hkex(row: dict[str, Any], source_url: str) -> CompanyDetails:
    code = row["code"]
    return CompanyDetails(
        id=code,
        name=row["name"],
        country="HK",
        status="listed",
        capital_currency="HKD",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=code,
                label="HKEX Stock Code",
            )
        ],
        raw=row,
        source_url=source_url,
    )


def _address_from_oc(row: dict[str, Any]) -> str | None:
    addr = row.get("registered_address_in_full") or row.get("registered_address")
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            addr.get("street_address"),
            addr.get("locality"),
            addr.get("region"),
            addr.get("postal_code"),
            addr.get("country"),
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    return None


def _status_from_oc(row: dict[str, Any]) -> str | None:
    s = row.get("current_status") or row.get("company_status")
    if not s:
        return None
    sl = str(s).lower()
    if any(tok in sl for tok in ("dissolved", "struck", "deregistered")):
        return "dissolved"
    if "active" in sl or "live" in sl:
        return "active"
    return str(s)


def _details_from_oc(company: dict[str, Any], cr: str) -> CompanyDetails:
    inc = company.get("incorporation_date")
    diss = company.get("dissolution_date")
    try:
        inc_d = date.fromisoformat(inc) if inc else None
    except (ValueError, TypeError):
        inc_d = None
    try:
        diss_d = date.fromisoformat(diss) if diss else None
    except (ValueError, TypeError):
        diss_d = None

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=cr,
            label="CR Number",
        )
    ]
    for ident in company.get("identifiers", []) or []:
        scheme = (ident.get("identifier_system_code") or "").lower()
        uid = str(ident.get("uid") or "").strip()
        if not uid:
            continue
        if "br_number" in scheme or "business_registration" in scheme:
            try:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.OTHER,
                        value=_normalize_br_number(uid),
                        label="BR Number",
                    )
                )
            except InvalidIdentifierError:
                pass

    return CompanyDetails(
        id=cr,
        name=(company.get("name") or "").strip(),
        country="HK",
        legal_form=company.get("company_type"),
        status=_status_from_oc(company),
        incorporation_date=inc_d,
        dissolution_date=diss_d,
        registered_address=_address_from_oc(company),
        capital_currency="HKD",
        identifiers=identifiers,
        raw=company,
        source_url=(
            company.get("opencorporates_url") or "https://www.icris.cr.gov.hk/csci/"
        ),
    )
