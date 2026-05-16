"""Cambodia adapter — MoC Online Business Registration + CSX (best-effort).

Two free, no-auth sources are stitched together here:

* businessregistration.moc.gov.kh — the Ministry of Commerce Online
  Business Registration portal. Its public search page exposes a JSON
  endpoint at ``/api/public/companies`` that returns name/registration-
  number/status snippets. No API key. Session-cookie session is created
  lazily on the first request.
* csx.com.kh — the Cambodia Securities Exchange. Listed issuers publish
  free annual reports under ``/en/listed-companies/profile/{TICKER}``.
  We never download the report bodies; only the canonical URL is
  emitted, and only after the ticker landing page returns 200.

Identifier:
  The MoC company registration number is an 8-digit zero-padded code
  printed on every Certificate of Incorporation (e.g. ``00012345``).
  Cambodian VAT TINs are 10-digit codes issued by the General
  Department of Taxation and frequently appear alongside the MoC
  number on the same record — ``COMPANY_NUMBER`` and ``VAT`` are both
  accepted on lookup.
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
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_MOC_NUMBER_RE = re.compile(r"^\d{1,10}$")
_VAT_TIN_RE = re.compile(r"^\d{9,10}$")
# CSX tickers are uppercase ASCII, 2–5 chars; we guard hard so we never
# synthesise a URL from a noisy field.
_CSX_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")

# Known CSX-listed issuers as of the MVP build. The mapping is keyed by
# normalised company-name token so a name search can surface a ticker
# even when the MoC payload omits one. Values are (ticker, currency).
_CSX_KNOWN: dict[str, tuple[str, str]] = {
    "acleda": ("ABC", "KHR"),
    "phnompenhspecialeconomiczone": ("PPSP", "KHR"),
    "ppsp": ("PPSP", "KHR"),
    "phnompenhwatersupplyauthority": ("PWSA", "KHR"),
    "ppwsa": ("PWSA", "KHR"),
    "pwsa": ("PWSA", "KHR"),
    "sihanoukvilleautonomousport": ("PAS", "KHR"),
    "pas": ("PAS", "KHR"),
    "grandtwins": ("GTI", "KHR"),
    "phnompenhautonomousport": ("PPAP", "KHR"),
    "ppap": ("PPAP", "KHR"),
}


def _normalize_moc_number(value: str) -> str:
    """Strip whitespace, dashes, dots and zero-pad to 8 digits.

    Pure-numeric inputs are zero-padded; alphanumeric inputs are rejected
    so we never silently coerce a TIN or a CSX ticker into a MoC slot.
    """
    if value is None:
        raise InvalidIdentifierError("Cambodia MoC number cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("KH"):
        cleaned = cleaned[2:]
    if not _MOC_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Cambodia MoC number must be 1–10 digits; got: {value}"
        )
    return cleaned.zfill(8) if len(cleaned) <= 8 else cleaned


def _normalize_vat_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-.]", "", str(value or "").strip())
    if cleaned.upper().startswith("KH"):
        cleaned = cleaned[2:]
    if not _VAT_TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Cambodia VAT TIN must be 9–10 digits; got: {value}"
        )
    return cleaned


def _parse_kh_date(s: Any) -> date | None:
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _pick(r: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _detect_csx_ticker(name: str, raw: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    """Return ``(ticker, currency)`` if we recognise a CSX listing.

    First trust an explicit ticker field on the payload (if it matches
    the strict ticker regex); otherwise fall back to the known-issuer
    name table. Never invent a ticker.
    """
    if raw:
        candidate = _pick(raw, "csx_symbol", "stockSymbol", "symbol", "Ticker")
        if candidate:
            t = str(candidate).strip().upper()
            if _CSX_TICKER_RE.match(t):
                return t, "KHR"
    slug = _slug(name)
    if not slug:
        return None, None
    for key, (ticker, ccy) in _CSX_KNOWN.items():
        if key in slug:
            return ticker, ccy
    return None, None


class KHAdapter(CountryAdapter):
    country_code = "KH"
    country_name = "Cambodia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    MOC_BASE = "https://www.businessregistration.moc.gov.kh"
    CSX_BASE = "https://csx.com.kh"

    def _moc_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "km;q=0.9, en;q=0.8",
            "Referer": f"{self.MOC_BASE}/",
            "Origin": self.MOC_BASE,
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.MOC_BASE, headers=self._moc_headers()
            ) as client:
                resp = await get_with_retry(client, "/")
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"businessregistration.moc.gov.kh HTTP {resp.status_code}",
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
            notes=(
                "Registry via businessregistration.moc.gov.kh public search. "
                "Financials best-effort: CSX annual-report URLs for listed "
                "issuers only; unlisted firms return []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        rows = await self._moc_search(query, limit)
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            moc = _pick(r, "registration_number", "registrationNumber", "regNo", "moc_number", "id")
            display = _pick(r, "name_en", "english_name", "nameEn", "name", "name_km", "title")
            if not (moc and display):
                continue
            moc_s = str(moc).strip()
            identifiers = [
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=moc_s,
                    label="MoC Number",
                )
            ]
            tin = _pick(r, "tin", "vat", "vat_tin", "VAT")
            if tin:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=str(tin).strip(),
                        label="Tax Identification Number",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=moc_s,
                    name=str(display).strip(),
                    country=self.country_code,
                    identifiers=identifiers,
                    address=_pick(r, "address_en", "address", "registered_address"),
                    status=_normalize_status(_pick(r, "status", "company_status")),
                    source_url=f"{self.MOC_BASE}/search?query={moc_s}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            moc = _normalize_moc_number(value)
            record = await self._moc_lookup(moc)
            if record is None:
                return None
            return _record_to_details(record, moc, self.MOC_BASE)
        if id_type == IdentifierType.VAT:
            tin = _normalize_vat_tin(value)
            rows = await self._moc_search(tin, 5)
            for r in rows:
                if _slug(str(_pick(r, "tin", "vat", "vat_tin", "VAT") or "")) == _slug(tin):
                    moc = _pick(r, "registration_number", "registrationNumber", "regNo")
                    if moc:
                        return _record_to_details(r, _normalize_moc_number(str(moc)), self.MOC_BASE)
            return None
        raise InvalidIdentifierError(
            f"Cambodia supports COMPANY_NUMBER or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        moc = _normalize_moc_number(company_id)
        record = await self._moc_lookup(moc) or {}
        name = str(_pick(record, "name_en", "english_name", "nameEn", "name") or "")
        ticker, ccy = _detect_csx_ticker(name, record)
        if not ticker:
            return []

        url = f"{self.CSX_BASE}/en/listed-companies/profile/{ticker}"
        filings: list[FinancialFiling] = []
        # Verify the CSX landing page actually exists before claiming a
        # filing is available — we never emit a fabricated URL.
        async with build_http_client(timeout=15.0) as client:
            try:
                probe = await client.get(url)
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if probe.status_code != 200:
                return []

        current_year = datetime.utcnow().year
        for year in range(current_year - years, current_year):
            filings.append(
                FinancialFiling(
                    company_id=moc,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency=ccy or "KHR",
                    document_url=url,
                    document_format="html",
                    source_url=url,
                )
            )
        return filings

    async def _moc_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        async with build_http_client(
            base_url=self.MOC_BASE, headers=self._moc_headers()
        ) as client:
            for path, params in (
                ("/api/public/companies", {"q": query, "limit": limit}),
                ("/api/public/companies/search", {"name": query, "limit": limit}),
            ):
                try:
                    resp = await get_with_retry(client, path, params=params)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code >= 400:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                rows = _extract_rows(payload)
                if rows:
                    return rows
        return []

    async def _moc_lookup(self, moc: str) -> dict[str, Any] | None:
        async with build_http_client(
            base_url=self.MOC_BASE, headers=self._moc_headers()
        ) as client:
            for path in (
                f"/api/public/companies/{moc}",
                f"/api/public/companies?registration_number={moc}",
            ):
                try:
                    resp = await get_with_retry(client, path)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code in (401, 403, 404):
                    continue
                if resp.status_code >= 400:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    inner = payload.get("data") or payload.get("company") or payload
                    if isinstance(inner, dict) and (
                        inner.get("registration_number")
                        or inner.get("registrationNumber")
                        or inner.get("regNo")
                        or inner.get("name")
                        or inner.get("name_en")
                    ):
                        return inner
                    rows = _extract_rows(payload)
                    if rows:
                        return rows[0]
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
                inner = v.get("data") or v.get("items") or v.get("rows")
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
    return []


def _normalize_status(s: Any) -> str | None:
    if not s:
        return None
    raw = str(s)
    lowered = raw.lower()
    if "active" in lowered or "operating" in lowered:
        return "active"
    if any(tok in lowered for tok in ("dissolved", "ceased", "deregistered", "struck")):
        return "ceased"
    return raw


def _record_to_details(
    r: dict[str, Any], moc: str, moc_base: str
) -> CompanyDetails:
    display = _pick(r, "name_en", "english_name", "nameEn", "name", "name_km", "title") or ""
    name = str(display).strip()
    address = _pick(r, "address_en", "address", "registered_address", "addressEn")
    legal_form = _pick(r, "legal_form", "company_type", "type", "form")
    status = _normalize_status(_pick(r, "status", "company_status"))
    inc_date = _parse_kh_date(
        _pick(r, "incorporation_date", "registration_date", "registeredOn", "registered_at")
    )
    capital = _coerce_float(_pick(r, "capital", "registered_capital", "capital_amount"))
    capital_ccy = _pick(r, "capital_currency", "currency") or ("KHR" if capital else None)
    isic = _pick(r, "isic", "business_activity", "main_activity")
    phone = _pick(r, "phone", "telephone", "contact_phone")
    email = _pick(r, "email", "contact_email")
    website = _pick(r, "website", "url")
    director_name = _pick(r, "director", "legal_representative", "ceo", "chairman")
    tin = _pick(r, "tin", "vat", "vat_tin", "VAT")

    directors = (
        [Director(name=str(director_name).strip())] if director_name else []
    )

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=moc,
            label="MoC Number",
        )
    ]
    if tin:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=str(tin).strip(),
                label="Tax Identification Number",
            )
        )

    return CompanyDetails(
        id=moc,
        name=name,
        country="KH",
        legal_form=str(legal_form) if legal_form else None,
        status=status,
        incorporation_date=inc_date,
        registered_address=str(address) if address else None,
        capital_amount=capital,
        capital_currency=str(capital_ccy) if capital_ccy else None,
        sic_codes=[str(isic)] if isic else [],
        identifiers=identifiers,
        directors=directors,
        website=str(website) if website else None,
        phone=str(phone) if phone else None,
        email=str(email) if email else None,
        raw=r,
        source_url=f"{moc_base}/search?query={moc}",
    )
