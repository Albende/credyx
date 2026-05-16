"""Philippines adapter — SEC iView + PSE Edge.

Two free, no-auth public sources are stitched together here:

* SEC iView (Securities and Exchange Commission of the Philippines). Public
  company viewer at https://iview.sec.gov.ph — used for name search and
  per-company registry lookup. No API key. The endpoints are not formally
  documented, so we probe a small set of well-known JSON paths and fall back
  to HTML parsing when only the SPA shell answers.
* PSE Edge (Philippine Stock Exchange) for listed-company annual reports.
  Each listed firm has a stable company-page URL keyed by ticker symbol.
  We only emit a `FinancialFiling` when the PSE page actually returns 200
  with a recognisable annual-report marker — we never invent.

Identifiers:
- COMPANY_NUMBER → SEC Registration Number. Alphanumeric, often prefixed
  with `CS`, `A`, `AS`, `AN`, or `PP`. Case-insensitive on input; preserved
  uppercased on output. Length is not fixed — anywhere from 6 to ~14 chars
  in practice.
- VAT            → 12-digit Tax Identification Number (TIN). The TIN is
  issued by the Bureau of Internal Revenue (BIR) and is independent of the
  SEC number; the SEC site does not link the two, so VAT lookup falls back
  to a name search by TIN string and returns None when no match surfaces.

Unlisted companies have no free filed-financials source — `fetch_financials`
returns `[]` rather than fabricate data, per the project's non-negotiables.
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

# SEC registration numbers are alphanumeric with an optional letter prefix
# (CS / A / AS / AN / PP). The body is 6-14 chars total — we keep the bound
# loose so historical numbers still validate.
_SEC_REG_RE = re.compile(r"^[A-Z0-9]{6,14}$")
_TIN_RE = re.compile(r"^\d{9,12}$")
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")


def _normalize_sec_number(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("PH"):
        cleaned = cleaned[2:]
    if not _SEC_REG_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Philippines SEC Registration Number invalid: {value}"
        )
    return cleaned


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Philippines TIN must be 9-12 digits, got: {value}"
        )
    return cleaned


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
    # SEC reports occasionally render dates as "MM/DD/YYYY" or "Month D, YYYY".
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


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("PHP", "").strip())
    except (TypeError, ValueError):
        return None


class PHAdapter(CountryAdapter):
    country_code = "PH"
    country_name = "Philippines"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    SEC_BASE = "https://iview.sec.gov.ph"
    PSE_BASE = "https://edge.pse.com.ph"
    PSE_PUBLIC_BASE = "https://www.pse.com.ph"

    def _sec_headers(self) -> dict[str, str]:
        # iView is an SPA — its JSON endpoints reject requests that don't
        # carry a browser-style Accept and a matching Referer.
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en;q=0.9",
            "Referer": f"{self.SEC_BASE}/",
            "Origin": self.SEC_BASE,
        }

    def _pse_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
            "Accept-Language": "en;q=0.9",
            "Referer": f"{self.PSE_PUBLIC_BASE}/",
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.SEC_BASE, headers=self._sec_headers()
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
                        notes=f"SEC iView HTTP {resp.status_code}",
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
                "Registry via SEC iView (no auth). Financials best-effort: "
                "PSE Edge URLs for listed firms only; unlisted firms return []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        rows = await self._sec_search(query, limit=limit)
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            sec_no = _pick(r, "sec_registration_no", "secRegNo", "regNo", "id")
            display = _pick(r, "company_name", "companyName", "name", "title")
            if not sec_no or not display:
                continue
            sec_no_str = str(sec_no).strip().upper()
            matches.append(
                CompanyMatch(
                    id=sec_no_str,
                    name=str(display).strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=sec_no_str,
                            label="SEC Registration Number",
                        ),
                    ],
                    address=_pick(r, "address", "registeredAddress"),
                    status=_normalize_status(_pick(r, "status", "companyStatus")),
                    source_url=f"{self.SEC_BASE}/#/company/{sec_no_str}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            sec_no = _normalize_sec_number(value)
            record = await self._sec_detail(sec_no)
            if record is None:
                # iView's search index is sometimes ahead of the detail shard.
                rows = await self._sec_search(sec_no, limit=1)
                if not rows:
                    return None
                record = rows[0]
            return _record_to_details(record, sec_no, self.SEC_BASE)
        if id_type == IdentifierType.VAT:
            tin = _normalize_tin(value)
            rows = await self._sec_search(tin, limit=1)
            if not rows:
                return None
            sec_no = str(
                _pick(rows[0], "sec_registration_no", "secRegNo", "regNo", "id") or ""
            ).strip().upper()
            if not sec_no:
                return None
            return _record_to_details(rows[0], sec_no, self.SEC_BASE)
        raise InvalidIdentifierError(
            f"Philippines supports COMPANY_NUMBER (SEC) or VAT (TIN), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        sec_no = _normalize_sec_number(company_id)
        record = await self._sec_detail(sec_no)
        if record is None:
            rows = await self._sec_search(sec_no, limit=1)
            record = rows[0] if rows else None
        symbol = _detect_pse_symbol(record) if record else None
        if not symbol:
            return []

        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        async with build_http_client(
            timeout=15.0, headers=self._pse_headers()
        ) as client:
            for year in range(current_year - years, current_year):
                url = (
                    f"{self.PSE_PUBLIC_BASE}/stockMarket/companyInfoSecurityProfile.html"
                    f"?cmpy_id={symbol}&security_id={symbol}&year={year}"
                )
                try:
                    resp = await client.get(url)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code != 200:
                    continue
                body = resp.text or ""
                # Same SPA shell answers for every URL — require a real
                # annual-report marker before we keep the link.
                if not any(
                    tok in body
                    for tok in (
                        "Annual Report",
                        "annual-report",
                        "Audited Financial Statement",
                        "17-A",
                    )
                ):
                    continue
                filings.append(
                    FinancialFiling(
                        company_id=sec_no,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="PHP",
                        document_url=url,
                        document_format="html",
                        source_url=(
                            f"{self.PSE_PUBLIC_BASE}/stockMarket/"
                            f"companyInfo.html?cmpy_id={symbol}"
                        ),
                    )
                )
        return filings

    async def _sec_search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        async with build_http_client(
            base_url=self.SEC_BASE, headers=self._sec_headers()
        ) as client:
            for path, params in (
                ("/api/company/search", {"q": query, "limit": limit}),
                ("/api/search", {"q": query, "limit": limit}),
                ("/api/companies", {"name": query, "limit": limit}),
            ):
                try:
                    resp = await get_with_retry(client, path, params=params)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                rows = _extract_rows(payload)
                if rows:
                    return rows
        return []

    async def _sec_detail(self, sec_no: str) -> dict[str, Any] | None:
        async with build_http_client(
            base_url=self.SEC_BASE, headers=self._sec_headers()
        ) as client:
            for path in (
                f"/api/company/{sec_no}",
                f"/api/companies/{sec_no}",
            ):
                try:
                    resp = await get_with_retry(client, path)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code == 404:
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    inner = payload.get("data") or payload.get("company") or payload
                    if isinstance(inner, dict) and inner:
                        return inner
        return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "rows", "companies"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
            if isinstance(v, dict):
                for inner_key in ("data", "items", "rows", "results"):
                    inner = v.get(inner_key)
                    if isinstance(inner, list):
                        return [r for r in inner if isinstance(r, dict)]
    return []


def _pick(r: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return None


def _normalize_status(s: Any) -> str | None:
    if not s:
        return None
    raw = str(s)
    lo = raw.lower()
    if any(tok in lo for tok in ("active", "existing", "registered", "operating")):
        return "active"
    if any(
        tok in lo
        for tok in ("revoked", "suspended", "dissolved", "delisted", "expired")
    ):
        return "ceased"
    return raw


def _detect_pse_symbol(record: dict[str, Any] | None) -> str | None:
    """Return a PSE ticker symbol if the SEC record marks the company as listed.

    SEC iView exposes the symbol under a handful of keys depending on the
    record shape; we only return a value that looks like a real ticker
    (1-6 chars, A-Z then A-Z0-9). Otherwise we'd be guessing.
    """
    if not record:
        return None
    candidate = _pick(
        record, "pseSymbol", "PSESymbol", "stockSymbol", "tickerSymbol", "symbol", "ticker"
    )
    if not candidate:
        return None
    raw = str(candidate).strip().upper()
    if _TICKER_RE.match(raw):
        return raw
    return None


def _record_to_details(
    r: dict[str, Any], sec_no: str, sec_base: str
) -> CompanyDetails:
    display_name = str(
        _pick(r, "company_name", "companyName", "name", "title") or ""
    ).strip()

    address = _pick(
        r,
        "principalOffice",
        "registeredAddress",
        "officeAddress",
        "address",
    )
    capital = _coerce_float(
        _pick(
            r,
            "authorizedCapital",
            "authorized_capital",
            "paidUpCapital",
            "capitalStock",
            "capital",
        )
    )
    legal_form = _pick(
        r, "companyType", "company_type", "corporationType", "legalForm"
    )
    status = _normalize_status(
        _pick(r, "companyStatus", "company_status", "status")
    )
    inc_date = _parse_ph_date(
        _pick(
            r,
            "registrationDate",
            "registration_date",
            "dateRegistered",
            "incorporationDate",
        )
    )
    industry = _pick(
        r, "industryCode", "industry_code", "psicCode", "psic", "industry"
    )
    tin = _pick(r, "tin", "TIN", "taxIdentificationNumber")

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=sec_no,
            label="SEC Registration Number",
        ),
    ]
    if tin:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=str(tin).strip(),
                label="TIN",
            )
        )

    return CompanyDetails(
        id=sec_no,
        name=display_name,
        country="PH",
        legal_form=str(legal_form) if legal_form else None,
        status=status,
        incorporation_date=inc_date,
        registered_address=str(address) if address else None,
        capital_amount=capital,
        capital_currency="PHP",
        sic_codes=[str(industry)] if industry else [],
        identifiers=identifiers,
        raw=r,
        source_url=f"{sec_base}/#/company/{sec_no}",
    )
