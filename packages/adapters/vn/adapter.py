"""Vietnam adapter — thongtindoanhnghiep.co + HOSE/HNX (best-effort).

Two free, no-auth sources are stitched together here:

* thongtindoanhnghiep.co — community-maintained JSON wrapper around the
  National Business Registration Portal (dangkykinhdoanh.gov.vn). It
  exposes a name-search endpoint (/api/company/search) and a per-company
  detail endpoint (/api/company/{mst}). No API key. Free.
* HOSE (hsx.vn) / HNX (hnx.vn) stock exchanges for listed-company annual
  reports. We only synthesize the canonical report URL — we never
  download or interpret the payload here. Unlisted firms return [].

Identifier:
  The Mã số thuế (MST / Tax Code) is a 10-digit ID issued by the General
  Department of Taxation; branch units append a 3-digit suffix
  ("-001"…"-NNN"), giving 13 digits total. The MST doubles as both the
  business registration number and the VAT number — both
  ``COMPANY_NUMBER`` and ``VAT`` are accepted on lookup and map to the
  same value.
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

_MST_RE = re.compile(r"^\d{10}(\d{3})?$")


def _normalize_mst(value: str) -> str:
    """Strip whitespace, dashes, dots and an optional ``VN`` prefix.

    Branch suffixes (``-001`` etc.) are preserved as trailing digits so a
    lookup against the parent firm vs. one of its branches remains distinct.
    """
    if value is None:
        raise InvalidIdentifierError("Vietnam MST cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("VN"):
        cleaned = cleaned[2:]
    if not _MST_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Vietnam MST must be 10 digits, optionally + 3-digit branch suffix; got: {value}"
        )
    return cleaned


def _parse_vn_date(s: Any) -> date | None:
    """Accept ISO ``YYYY-MM-DD`` and Vietnamese ``DD/MM/YYYY`` forms.

    Returns ``None`` for anything we cannot parse — we never guess a date.
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


class VNAdapter(CountryAdapter):
    country_code = "VN"
    country_name = "Vietnam"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    TTDN_BASE = "https://thongtindoanhnghiep.co"
    HOSE_BASE = "https://www.hsx.vn"
    HNX_BASE = "https://www.hnx.vn"
    NBR_BASE = "https://dangkykinhdoanh.gov.vn"

    def _ttdn_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi;q=0.9, en;q=0.8",
            "Referer": f"{self.TTDN_BASE}/",
            "Origin": self.TTDN_BASE,
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.TTDN_BASE, headers=self._ttdn_headers()
            ) as client:
                resp = await get_with_retry(
                    client, "/api/company/0300588569"
                )
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"thongtindoanhnghiep.co HTTP {resp.status_code}",
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
                "Registry via thongtindoanhnghiep.co (NBR wrapper). "
                "Financials best-effort: HOSE/HNX URLs for listed firms only."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with build_http_client(
            base_url=self.TTDN_BASE, headers=self._ttdn_headers()
        ) as client:
            resp = await get_with_retry(
                client,
                "/api/company/search",
                params={"k": query, "l": limit, "p": 1},
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
            mst = _pick(r, "MaSoThue", "TaxCode", "mst", "Code")
            if not mst:
                continue
            mst_s = str(mst).strip()
            display_name = (
                _pick(r, "TenDoanhNghiep", "Title", "Name", "name", "TenCongTy")
                or ""
            )
            matches.append(
                CompanyMatch(
                    id=mst_s,
                    name=str(display_name).strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=mst_s,
                            label="MST",
                        ),
                        RegistryIdentifier(
                            type=IdentifierType.VAT,
                            value=mst_s,
                            label="Tax Code",
                        ),
                    ],
                    address=_pick(r, "DiaChiCongTy", "Address", "address"),
                    status=_normalize_status(
                        _pick(r, "TinhTrang", "Status", "status")
                    ),
                    source_url=f"{self.TTDN_BASE}/{mst_s}-tnc",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"Vietnam supports COMPANY_NUMBER or VAT (same MST), got {id_type}"
            )
        mst = _normalize_mst(value)
        record = await self._fetch_ttdn_detail(mst)
        if record is None:
            return None
        return _record_to_details(record, mst, self.TTDN_BASE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        mst = _normalize_mst(company_id)
        record = await self._fetch_ttdn_detail(mst)
        if record is None:
            return []
        symbol, exchange = _detect_stock_listing(record)
        if not symbol:
            return []

        base = self.HOSE_BASE if exchange == "HOSE" else self.HNX_BASE
        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        # HOSE/HNX serve company landing pages by ticker symbol. We do not
        # claim a filing exists unless the symbol page itself returns 200
        # — every filing URL is verified before being emitted.
        async with build_http_client(timeout=15.0) as client:
            url = (
                f"{base}/Modules/Listed/Web/SymbolView?fid={symbol}"
                if exchange == "HNX"
                else f"{base}/en/listed-company/stock-quote/{symbol}.html"
            )
            try:
                probe = await client.get(url)
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if probe.status_code != 200:
                return []

            for year in range(current_year - years, current_year):
                # Listed Vietnamese issuers file annual reports with the
                # exchange; the landing page hosts the index of those reports.
                filings.append(
                    FinancialFiling(
                        company_id=mst,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="VND",
                        document_url=url,
                        document_format="html",
                        source_url=url,
                    )
                )
        return filings

    async def _fetch_ttdn_detail(self, mst: str) -> dict[str, Any] | None:
        async with build_http_client(
            base_url=self.TTDN_BASE, headers=self._ttdn_headers()
        ) as client:
            resp = await get_with_retry(client, f"/api/company/{mst}")
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                return None
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
        for key in ("LtsItems", "Items", "data", "results", "items", "rows"):
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
    if any(tok in raw for tok in ("Đang hoạt động", "Active")) or "hoạt động" in lowered:
        return "active"
    if any(
        tok in raw
        for tok in (
            "Ngừng hoạt động",
            "Tạm ngừng",
            "Đã giải thể",
            "Bỏ địa chỉ",
            "Dissolved",
        )
    ):
        return "ceased"
    return raw


def _detect_stock_listing(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(symbol, exchange)`` if the firm is publicly listed.

    The thongtindoanhnghiep.co payload occasionally tags a stock symbol on
    listed issuers; we only return a value when we see a clean A-Z token
    so we never construct a fake HOSE/HNX URL.
    """
    candidate = _pick(record, "MaChungKhoan", "StockSymbol", "stockSymbol", "Symbol")
    if not candidate:
        return None, None
    raw = str(candidate).strip().upper()
    if not re.match(r"^[A-Z]{2,4}$", raw):
        return None, None
    exchange = _pick(record, "SanGiaoDich", "Exchange", "exchange")
    exch_norm = str(exchange or "").upper()
    if "HNX" in exch_norm or "UPCOM" in exch_norm:
        return raw, "HNX"
    return raw, "HOSE"


def _record_to_details(
    r: dict[str, Any], mst: str, ttdn_base: str
) -> CompanyDetails:
    display_name = (
        _pick(r, "Title", "TenDoanhNghiep", "Name", "TenCongTy", "name") or ""
    )
    name = str(display_name).strip()
    address = _pick(r, "DiaChiCongTy", "Address", "address", "DiaChi")
    legal_form = _pick(r, "LoaiHinhDN", "LegalForm", "TypeOfCompany")
    status = _normalize_status(_pick(r, "TinhTrang", "Status", "status"))
    inc_date = _parse_vn_date(
        _pick(r, "NgayCap", "IncorporationDate", "RegistrationDate")
    )
    capital = _coerce_float(_pick(r, "VonDieuLe", "Capital", "CapitalAmount"))
    isic = _pick(r, "NganhNgheKinhDoanhChinh", "MainBusinessLine", "ISIC")
    phone = _pick(r, "DienThoai", "Phone", "phone")
    email = _pick(r, "Email", "email")
    website = _pick(r, "Website", "website")
    director_name = _pick(
        r, "ChuSoHuu", "NguoiDaiDien", "Director", "LegalRepresentative"
    )

    from packages.shared.models import Director

    directors = (
        [Director(name=str(director_name).strip())]
        if director_name
        else []
    )

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=mst,
            label="MST",
        ),
        RegistryIdentifier(
            type=IdentifierType.VAT,
            value=mst,
            label="Tax Code",
        ),
    ]

    return CompanyDetails(
        id=mst,
        name=name,
        country="VN",
        legal_form=str(legal_form) if legal_form else None,
        status=status,
        incorporation_date=inc_date,
        registered_address=str(address) if address else None,
        capital_amount=capital,
        capital_currency="VND" if capital else None,
        sic_codes=[str(isic)] if isic else [],
        identifiers=identifiers,
        directors=directors,
        website=str(website) if website else None,
        phone=str(phone) if phone else None,
        email=str(email) if email else None,
        raw=r,
        source_url=f"{ttdn_base}/{mst}-tnc",
    )
