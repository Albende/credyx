"""Thailand adapter — DBD DataWarehouse + SET (Stock Exchange of Thailand).

Two free, no-auth public sources are stitched together here:

* DBD DataWarehouse (Department of Business Development, Ministry of
  Commerce). Public JSON endpoints behind https://datawarehouse.dbd.go.th
  drive both the name search and the per-company detail page. No API key.
* SET (Stock Exchange of Thailand) for listed-company annual financial
  statements. We synthesize the canonical statement URL per year — we do
  not download the payload. Unlisted firms return [].

Identifier:
  The 13-digit Juristic Person ID issued by DBD doubles as the company's
  tax ID (VAT) and registration number. Both `COMPANY_NUMBER` and `VAT`
  are accepted on lookup and map to the same value.
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

_JURISTIC_ID_RE = re.compile(r"^\d{13}$")


def _normalize_juristic_id(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if cleaned.upper().startswith("TH"):
        cleaned = cleaned[2:]
    if not _JURISTIC_ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Thailand Juristic Person ID must be exactly 13 digits, got: {value}"
        )
    return cleaned


def _parse_th_date(s: Any) -> date | None:
    """DBD returns dates as ISO 'YYYY-MM-DD' or Buddhist-era 'DD/MM/YYYY+543'.

    We accept ISO directly, and translate Buddhist-era to Gregorian when the
    year is clearly > 2400 (B.E. epoch). Anything else returns None — we never
    guess.
    """
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year > 2400:
            year -= 543
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


class THAdapter(CountryAdapter):
    country_code = "TH"
    country_name = "Thailand"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    DBD_BASE = "https://datawarehouse.dbd.go.th"
    SET_BASE = "https://www.set.or.th"

    def _dbd_headers(self) -> dict[str, str]:
        # DBD's JSON endpoints reject requests without a browser-style Accept
        # header and matching Referer — the site is SPA-driven.
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en;q=0.8, th;q=0.9",
            "Referer": f"{self.DBD_BASE}/",
            "Origin": self.DBD_BASE,
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.DBD_BASE, headers=self._dbd_headers()
            ) as client:
                resp = await get_with_retry(
                    client,
                    "/api/search",
                    params={"key": "0107544000108", "page": 1, "pageSize": 1},
                )
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"DBD HTTP {resp.status_code}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Registry via DBD DataWarehouse. Financials best-effort: SET URLs for listed firms only.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with build_http_client(
            base_url=self.DBD_BASE, headers=self._dbd_headers()
        ) as client:
            resp = await get_with_retry(
                client,
                "/api/search",
                params={"key": query, "page": 1, "pageSize": limit},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                return []

        rows = _extract_search_rows(payload)
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            juristic = _pick(r, "juristicId", "JuristicID", "id", "JuristicId")
            if not juristic:
                continue
            juristic = str(juristic).strip()
            display_name = (
                _pick(r, "JuristicNameEN", "juristicNameEN", "nameEn")
                or _pick(r, "JuristicNameTH", "juristicNameTH", "nameTh", "name")
                or ""
            )
            matches.append(
                CompanyMatch(
                    id=juristic,
                    name=str(display_name).strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=juristic,
                            label="Juristic Person ID",
                        ),
                    ],
                    address=_pick(r, "address", "JuristicAddress"),
                    status=_normalize_status(
                        _pick(r, "juristicStatus", "JuristicStatus", "status")
                    ),
                    source_url=f"{self.DBD_BASE}/company/{juristic}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"Thailand supports COMPANY_NUMBER or VAT (same 13-digit ID), got {id_type}"
            )
        juristic = _normalize_juristic_id(value)
        record = await self._fetch_dbd_detail(juristic)
        if record is None:
            return None
        return _record_to_details(record, juristic, self.DBD_BASE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        juristic = _normalize_juristic_id(company_id)
        record = await self._fetch_dbd_detail(juristic)
        if record is None:
            return []
        symbol = _detect_set_symbol(record)
        if not symbol:
            return []

        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        # SET hosts annual statements per listed symbol behind a stable URL.
        # We probe each year over the requested window and only emit a filing
        # when the page actually returns 200 — we never invent.
        async with build_http_client(timeout=15.0) as client:
            for year in range(current_year - years, current_year):
                url = (
                    f"{self.SET_BASE}/en/market/product/stock/quote/"
                    f"{symbol}/financial-statement/company-highlights"
                    f"?period=annual&year={year}"
                )
                try:
                    resp = await client.get(url)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code != 200:
                    continue
                body = resp.text or ""
                # SET serves the same SPA shell for both "exists" and "no data".
                # Require a known financial-page marker before keeping the URL.
                if not any(
                    tok in body
                    for tok in ("financial-statement", "Financial Statement", "Annual")
                ):
                    continue
                filings.append(
                    FinancialFiling(
                        company_id=juristic,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="THB",
                        document_url=url,
                        document_format="html",
                        source_url=(
                            f"{self.SET_BASE}/en/market/product/stock/quote/"
                            f"{symbol}/financial-statement"
                        ),
                    )
                )
        return filings

    async def _fetch_dbd_detail(self, juristic: str) -> dict[str, Any] | None:
        async with build_http_client(
            base_url=self.DBD_BASE, headers=self._dbd_headers()
        ) as client:
            resp = await get_with_retry(client, f"/api/company/{juristic}")
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                # Some shards expose the same data through /api/search with the
                # juristic ID as the key — fall back rather than 500 the caller.
                fallback = await get_with_retry(
                    client,
                    "/api/search",
                    params={"key": juristic, "page": 1, "pageSize": 1},
                )
                if fallback.status_code != 200:
                    return None
                try:
                    payload = fallback.json()
                except ValueError:
                    return None
                rows = _extract_search_rows(payload)
                return rows[0] if rows else None
            try:
                payload = resp.json()
            except ValueError:
                return None
        if isinstance(payload, dict):
            inner = payload.get("data") or payload.get("company") or payload
            if isinstance(inner, dict):
                return inner
        return None


def _extract_search_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "rows"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
            if isinstance(v, dict):
                inner = v.get("data") or v.get("items") or v.get("rows")
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
    if any(tok in raw for tok in ("ยังดำเนินกิจการ", "Active", "active", "ดำเนินกิจการ")):
        return "active"
    if any(tok in raw for tok in ("เลิก", "เสร็จการชำระบัญชี", "Dissolved", "ร้าง")):
        return "ceased"
    return raw


def _detect_set_symbol(record: dict[str, Any]) -> str | None:
    """Pull a SET ticker symbol off the DBD record when the company is listed.

    DBD does not natively expose the SET symbol; some shards include it under
    `setSymbol` or as a tagged remark. We only return a symbol when it appears
    as a clean A-Z 1–8-char token — otherwise we'd be guessing.
    """
    candidate = _pick(record, "setSymbol", "stockSymbol", "symbol", "SETSymbol")
    if not candidate:
        return None
    raw = str(candidate).strip().upper()
    if re.match(r"^[A-Z][A-Z0-9\-&]{0,7}$", raw):
        return raw
    return None


def _record_to_details(
    r: dict[str, Any], juristic: str, dbd_base: str
) -> CompanyDetails:
    name_en = _pick(r, "JuristicNameEN", "juristicNameEN", "nameEn")
    name_th = _pick(r, "JuristicNameTH", "juristicNameTH", "nameTh", "name")
    display_name = str(name_en or name_th or "").strip()

    address = _pick(
        r,
        "JuristicAddress",
        "address",
        "RegisteredAddress",
        "registeredAddress",
    )
    capital = _coerce_float(
        _pick(r, "RegisterCapital", "registerCapital", "capital", "CapitalAmount")
    )
    legal_form = _pick(
        r, "JuristicType", "juristicType", "companyType", "legalForm"
    )
    status = _normalize_status(
        _pick(r, "JuristicStatus", "juristicStatus", "status")
    )
    inc_date = _parse_th_date(
        _pick(r, "RegisterDate", "registerDate", "incorporationDate")
    )
    tsic = _pick(r, "TSICCode", "tsicCode", "TSIC", "businessCode")

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=juristic,
            label="Juristic Person ID",
        ),
        RegistryIdentifier(
            type=IdentifierType.VAT,
            value=juristic,
            label="Tax ID",
        ),
    ]

    return CompanyDetails(
        id=juristic,
        name=display_name,
        country="TH",
        legal_form=str(legal_form) if legal_form else None,
        status=status,
        incorporation_date=inc_date,
        registered_address=str(address) if address else None,
        capital_amount=capital,
        capital_currency="THB",
        sic_codes=[str(tsic)] if tsic else [],
        identifiers=identifiers,
        raw=r,
        source_url=f"{dbd_base}/company/{juristic}",
    )
