"""Vietnam adapter — thongtindoanhnghiep.co (registry) + Vietcap (financials).

Three free, no-auth sources are stitched together here:

* ``thongtindoanhnghiep.co`` — community-maintained JSON wrapper around the
  National Business Registration Portal (dangkykinhdoanh.gov.vn). It exposes
  a name-search endpoint (``/api/company?k=``) and a per-company detail
  endpoint (``/api/company/{mst}``). No API key. The site sits behind a
  Cloudflare "Just a moment" wall, so requests go through
  ``fetch_with_bot_bypass`` (FlareSolverr).
* Vietcap IQ Insight service (``iq.vietcap.com.vn``) — the public data layer
  behind trading.vietcap.com.vn. Provides the full listed-company roster
  (used to resolve a tax code to its stock ticker via legal-name match) and
  audited annual financial statements (balance sheet + income statement) for
  every HOSE/HNX/UPCOM issuer. No API key, plain JSON.

Only listed issuers have financials; unlisted firms return ``[]``. Figures
returned in ``structured_data`` are the real, as-filed values served by
Vietcap — nothing is computed or invented here.

Identifier:
  The Mã số thuế (MST / Tax Code) is a 10-digit ID issued by the General
  Department of Taxation; branch units append a 3-digit suffix
  ("-001"…"-NNN"), giving 13 digits total. The MST doubles as both the
  business registration number and the VAT number — both ``COMPANY_NUMBER``
  and ``VAT`` are accepted on lookup and map to the same value.
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, fetch_with_bot_bypass
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

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


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


def _norm_name(value: Any) -> str:
    """ASCII-fold + lowercase a Vietnamese legal name to a comparable key.

    Đ/đ are mapped to ``d`` before combining-mark stripping; everything else
    non-alphanumeric collapses to single spaces. The normalized legal name is
    identical between the registry's SolrID slug and Vietcap's Vietnamese
    ``name`` field, which is what makes the tax-code → ticker join reliable.
    """
    s = str(value or "").replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _json_from_body(body: str | None) -> Any:
    """Parse JSON that may be wrapped in a FlareSolverr HTML ``<pre>`` block."""
    if not body:
        return None
    txt = body.strip()
    try:
        return json.loads(txt)
    except ValueError:
        pass
    m = re.search(r"<pre[^>]*>(.*?)</pre>", txt, re.S)
    if m:
        try:
            return json.loads(_html.unescape(m.group(1)))
        except ValueError:
            return None
    return None


_BS_TITLE_TARGETS: dict[str, tuple[str, ...]] = {
    "total_assets": ("total assets",),
    "current_assets": ("current assets",),
    "non_current_assets": ("long-term assets",),
    "cash_and_equivalents": ("cash and cash equivalents",),
    "inventories": ("inventories, net", "inventories"),
    "trade_receivables": ("accounts receivable",),
    "total_liabilities": ("liabilities",),
    "current_liabilities": ("current liabilities",),
    "non_current_liabilities": ("long-term liabilities",),
    "total_equity": ("owner's equity",),
    "share_capital": ("paid-in capital",),
    "retained_earnings": ("undistributed earnings",),
}

_IS_TITLE_TARGETS: dict[str, tuple[str, ...]] = {
    "revenue": ("net sales", "sales"),
    "gross_profit": ("gross profit",),
    "operating_profit": ("operating profit/(loss)",),
    "net_income": ("net profit/(loss) after tax",),
    "interest_expense": ("interest expenses",),
}


def _code_by_title(metric_rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in metric_rows:
        title = str(m.get("fullTitleEn") or m.get("titleEn") or "").strip().lower()
        field = m.get("field")
        if title and field and title not in out:
            out[title] = str(field)
    return out


def _map_line_items(
    row: dict[str, Any],
    code_by_title: dict[str, str],
    targets: dict[str, tuple[str, ...]],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for canonical, titles in targets.items():
        for title in titles:
            code = code_by_title.get(title)
            if code is None:
                continue
            val = _coerce_float(row.get(code))
            if val is not None:
                out[canonical] = val
                break
    return out


_listing_cache: list[dict[str, Any]] | None = None
_listing_lock = asyncio.Lock()


class VNAdapter(CountryAdapter):
    country_code = "VN"
    country_name = "Vietnam"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    TTDN_BASE = "https://thongtindoanhnghiep.co"
    NBR_BASE = "https://dangkykinhdoanh.gov.vn"
    VCI_IQ_BASE = "https://iq.vietcap.com.vn/api/iq-insight-service"

    def _vci_headers(self) -> dict[str, str]:
        return {
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://trading.vietcap.com.vn/",
            "Origin": "https://trading.vietcap.com.vn",
        }

    async def _ttdn_json(self, path: str) -> Any:
        url = f"{self.TTDN_BASE}{path}"
        body, status, _source = await fetch_with_bot_bypass(url, timeout=30.0)
        if status >= 400:
            return None
        return _json_from_body(body)

    async def _vci_json(self, url: str) -> Any:
        async with build_http_client(
            timeout=25.0, headers=self._vci_headers()
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return None
            try:
                return resp.json()
            except ValueError:
                return None

    async def health_check(self) -> AdapterHealth:
        try:
            record = await self._ttdn_json("/api/company/0300588569")
            if not isinstance(record, dict) or not record.get("MaSoThue"):
                return AdapterHealth(
                    country_code=self.country_code,
                    name=self.country_name,
                    status=AdapterStatus.ERROR,
                    capabilities={"search": False, "lookup": False, "financials": False},
                    notes="thongtindoanhnghiep.co returned no company record",
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
                "Registry via thongtindoanhnghiep.co (NBR wrapper, Cloudflare "
                "bypass). Financials via Vietcap IQ for listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        payload = await self._ttdn_json(f"/api/company?k={quote(query)}&p=1")
        rows = _extract_search_rows(payload)
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            mst = _pick(r, "MaSoThue", "TaxCode", "mst", "Code")
            if not mst:
                continue
            mst_s = str(mst).strip()
            display_name = (
                _pick(r, "TenDoanhNghiep", "Title", "Name", "name", "TenCongTy")
                or _name_from_solrid(r.get("SolrID"), mst_s)
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
        record = await self._ttdn_json(f"/api/company/{mst}")
        if not isinstance(record, dict) or not record.get("MaSoThue"):
            return None
        return _record_to_details(record, mst, self.TTDN_BASE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        mst = _normalize_mst(company_id)
        record = await self._ttdn_json(f"/api/company/{mst}")
        if not isinstance(record, dict):
            return []

        name_key = _norm_name(_name_from_solrid(record.get("SolrID"), mst))
        if not name_key:
            name_key = _norm_name(_pick(record, "Title", "TenDoanhNghiep"))
        if not name_key:
            return []

        ticker = await self._resolve_ticker(name_key)
        if not ticker:
            return []

        return await self._vci_financials(mst, ticker, years)

    async def _resolve_ticker(self, name_key: str) -> str | None:
        listing = await self._vci_listing()
        hits = {
            str(row.get("code")).upper()
            for row in listing
            if row.get("code") and _norm_name(row.get("name")) == name_key
        }
        if len(hits) == 1:
            return next(iter(hits))
        return None

    async def _vci_listing(self) -> list[dict[str, Any]]:
        global _listing_cache
        if _listing_cache is not None:
            return _listing_cache
        async with _listing_lock:
            if _listing_cache is not None:
                return _listing_cache
            payload = await self._vci_json(
                f"{self.VCI_IQ_BASE}/v2/company/search-bar?language=1"
            )
            data = payload.get("data") if isinstance(payload, dict) else payload
            _listing_cache = [r for r in data if isinstance(r, dict)] if data else []
            return _listing_cache

    async def _vci_financials(
        self, mst: str, ticker: str, years: int
    ) -> list[FinancialFiling]:
        metrics = await self._vci_json(
            f"{self.VCI_IQ_BASE}/v1/company/{ticker}/financial-statement/metrics"
        )
        metrics_data = metrics.get("data") if isinstance(metrics, dict) else None
        if not isinstance(metrics_data, dict):
            return []
        bs_titles = _code_by_title(metrics_data.get("BALANCE_SHEET") or [])
        is_titles = _code_by_title(metrics_data.get("INCOME_STATEMENT") or [])

        bs_rows = await self._vci_statement(ticker, "BALANCE_SHEET")
        is_rows = await self._vci_statement(ticker, "INCOME_STATEMENT")
        if not bs_rows and not is_rows:
            return []

        is_by_year = {r.get("yearReport"): r for r in is_rows}
        source_url = (
            f"{self.VCI_IQ_BASE}/v1/company/{ticker}/financial-statement"
        )

        filings: list[FinancialFiling] = []
        for bs in sorted(bs_rows, key=lambda r: r.get("yearReport") or 0, reverse=True):
            year = bs.get("yearReport")
            if not isinstance(year, int):
                continue
            income = is_by_year.get(year, {})
            balance_sheet = _map_line_items(bs, bs_titles, _BS_TITLE_TARGETS)
            income_statement = _map_line_items(income, is_titles, _IS_TITLE_TARGETS)
            if not balance_sheet and not income_statement:
                continue
            structured = {
                "currency": "VND",
                "period_end": date(year, 12, 31).isoformat(),
                "ticker": ticker,
                "balance_sheet": balance_sheet,
                "income_statement": income_statement,
                "raw_concepts": {
                    "balance_sheet": {
                        k: v for k, v in bs.items() if isinstance(v, (int, float))
                    },
                    "income_statement": {
                        k: v for k, v in income.items() if isinstance(v, (int, float))
                    },
                },
            }
            filings.append(
                FinancialFiling(
                    company_id=mst,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="VND",
                    structured_data=structured,
                    document_format="json",
                    source_url=source_url,
                )
            )
            if len(filings) >= years:
                break
        return filings

    async def _vci_statement(
        self, ticker: str, section: str
    ) -> list[dict[str, Any]]:
        payload = await self._vci_json(
            f"{self.VCI_IQ_BASE}/v1/company/{ticker}/financial-statement?section={section}"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return []
        rows = data.get("years") or []
        return [r for r in rows if isinstance(r, dict)]


def _name_from_solrid(solr_id: Any, mst: str) -> str | None:
    """Extract the slugged legal name from a ``/{mst}-{slug}`` SolrID.

    The registry's ``Title`` field is occasionally a stale branch/unit name,
    but the SolrID slug carries the registered legal name (ASCII, hyphenated)
    — which is exactly what the ticker join needs.
    """
    if not solr_id:
        return None
    slug = str(solr_id).lstrip("/")
    prefix = f"{mst}-"
    if slug.startswith(prefix):
        slug = slug[len(prefix) :]
    slug = slug.replace("-", " ").strip()
    return slug or None


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


def _record_to_details(
    r: dict[str, Any], mst: str, ttdn_base: str
) -> CompanyDetails:
    display_name = (
        _pick(r, "Title", "TenDoanhNghiep", "Name", "TenCongTy", "name")
        or _name_from_solrid(r.get("SolrID"), mst)
        or ""
    )
    name = str(display_name).strip()
    address = _pick(r, "DiaChiCongTy", "Address", "address", "DiaChi")
    legal_form = _pick(r, "LoaiHinhTitle", "LoaiHinhDN", "LegalForm", "TypeOfCompany")
    status = _normalize_status(_pick(r, "TinhTrang", "Status", "status"))
    inc_date = _parse_vn_date(
        _pick(r, "NgayCap", "IncorporationDate", "RegistrationDate")
    )
    capital = _coerce_float(_pick(r, "VonDieuLe", "Capital", "CapitalAmount"))
    isic = _pick(r, "NganhNgheTitle", "NganhNgheKinhDoanhChinh", "MainBusinessLine", "ISIC")
    phone = _pick(r, "NoiDangKyQuanLy_DienThoai", "DienThoai", "Phone", "phone")
    email = _pick(r, "Email", "email")
    website = _pick(r, "Website", "website")
    director_name = _pick(
        r, "ChuSoHuu", "GiamDoc", "NguoiDaiDien", "Director", "LegalRepresentative"
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
