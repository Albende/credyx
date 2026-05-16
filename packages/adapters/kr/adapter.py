"""KR adapter — OpenDART (FSS Data Analysis, Retrieval and Transfer system).

OpenDART exposes Korean Financial Supervisory Service filings, including
audited annual reports and structured account-level financial summaries for
listed and large unlisted reporting entities.

API docs: https://opendart.fss.or.kr/guide/main.do
Auth:     API key in `crtfc_key` query string. Free signup at
          https://opendart.fss.or.kr/uss/umt/EgovMberInsertView.do
Rate:     10,000 requests / day / key. Set per-minute throttle to 100.
Free:     Yes.

Scope note: OpenDART only indexes entities that file with the FSS — listed
companies (KOSPI/KOSDAQ/KONEX), large unlisted companies subject to
external audit, and a handful of other reporting types. Small private
firms with only a 사업자등록번호 (Business Registration Number) and no FSS
filing obligation are not in OpenDART; for those, NTS/HomeTax-side
lookups would be needed and are out of scope.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree as ET

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_CORP_CODE_RE = re.compile(r"^\d{1,8}$")
_STOCK_CODE_RE = re.compile(r"^\d{6}$")
_BIZ_REG_RE = re.compile(r"^\d{10}$")

_NO_DATA_STATUS = {"013"}
_AUTH_ERROR_STATUS = {"010", "011", "020"}
_QUOTA_STATUS = {"020"}


def _normalize_corp_code(value: str) -> str:
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if not _CORP_CODE_RE.match(cleaned):
        raise InvalidIdentifierError(f"KR corp_code invalid: {value}")
    return cleaned.zfill(8)


def _normalize_biz_reg(value: str) -> str:
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if not _BIZ_REG_RE.match(cleaned):
        raise InvalidIdentifierError(f"KR Business Registration Number invalid: {value}")
    return cleaned


def _normalize_stock_code(value: str) -> str:
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if not _STOCK_CODE_RE.match(cleaned):
        raise InvalidIdentifierError(f"KR stock code invalid: {value}")
    return cleaned


class KRAdapter(CountryAdapter):
    country_code = "KR"
    country_name = "South Korea"
    identifier_types = [
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.VAT,
        IdentifierType.OTHER,
    ]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = "KR_OPENDART_API_KEY"
    rate_limit_per_minute = 100

    BASE_URL = "https://opendart.fss.or.kr"
    DART_VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do"

    _corp_code_cache: list[dict[str, str]] | None = None

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv(self.api_key_env)

    def _client(self) -> Any:
        return build_http_client(base_url=self.BASE_URL)

    def _require_key(self) -> str:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        return self.api_key

    async def health_check(self) -> AdapterHealth:
        if not self.api_key:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                notes=f"Set {self.api_key_env} to enable.",
            )
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    "/api/list.json",
                    params={
                        "crtfc_key": self.api_key,
                        "corp_code": "00126380",
                        "bgn_de": "20240101",
                        "end_de": "20240131",
                        "pblntf_ty": "A",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                status = str(payload.get("status", ""))
                if status in _AUTH_ERROR_STATUS:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        requires_api_key=True,
                        api_key_present=True,
                        notes=f"OpenDART rejected key (status={status}).",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=True,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="OpenDART — covers listed and large external-audit entities only.",
        )

    async def _load_corp_codes(self) -> list[dict[str, str]]:
        """Cache the full OpenDART corp-code list (one fetch per process).

        The list endpoint returns a ZIP containing a single CORPCODE.xml file
        with every entity that has an OpenDART corp_code. Stock-listed firms
        have a non-empty `stock_code`; unlisted external-audit firms do not.
        """
        if KRAdapter._corp_code_cache is not None:
            return KRAdapter._corp_code_cache
        key = self._require_key()
        async with self._client() as client:
            resp = await get_with_retry(
                client, "/api/corpCode.xml", params={"crtfc_key": key}
            )
            resp.raise_for_status()
            content = resp.content
        # OpenDART returns either a ZIP (on success) or a small JSON body on
        # error — sniff by magic header so we can surface auth failures.
        if not content.startswith(b"PK"):
            try:
                payload = resp.json()
                raise AdapterError(
                    f"OpenDART corpCode error status={payload.get('status')} "
                    f"message={payload.get('message')}"
                )
            except ValueError:
                raise AdapterError("OpenDART corpCode did not return a ZIP.")

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
            if not xml_name:
                raise AdapterError("OpenDART corpCode ZIP missing XML.")
            xml_bytes = zf.read(xml_name)

        root = ET.fromstring(xml_bytes)
        out: list[dict[str, str]] = []
        for node in root.findall("list"):
            out.append(
                {
                    "corp_code": (node.findtext("corp_code") or "").strip(),
                    "corp_name": (node.findtext("corp_name") or "").strip(),
                    "stock_code": (node.findtext("stock_code") or "").strip(),
                    "modify_date": (node.findtext("modify_date") or "").strip(),
                }
            )
        KRAdapter._corp_code_cache = out
        return out

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._load_corp_codes()
        needle = name.strip().lower()
        if not needle:
            return []

        scored: list[tuple[int, dict[str, str]]] = []
        for r in rows:
            cn = r["corp_name"].lower()
            if not cn:
                continue
            if needle in cn:
                # Prefer prefix matches, then listed (has stock_code) over unlisted.
                prefix = 0 if cn.startswith(needle) else 1
                listed = 0 if r["stock_code"] else 1
                scored.append((prefix * 2 + listed, r))
        scored.sort(key=lambda x: x[0])

        matches: list[CompanyMatch] = []
        for _, r in scored[:limit]:
            corp_code = r["corp_code"]
            identifiers = [
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=corp_code,
                    label="OpenDART corp_code",
                ),
            ]
            if r["stock_code"]:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.OTHER,
                        value=r["stock_code"],
                        label="Stock code",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=corp_code,
                    name=r["corp_name"],
                    country=self.country_code,
                    identifiers=identifiers,
                    address=None,
                    status="listed" if r["stock_code"] else "unlisted_reporting",
                    source_url=(
                        f"https://dart.fss.or.kr/dsae001/selectPopup.ax?selectKey={corp_code}"
                    ),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        key = self._require_key()

        if id_type == IdentifierType.COMPANY_NUMBER:
            corp_code = _normalize_corp_code(value)
        elif id_type == IdentifierType.OTHER:
            stock = _normalize_stock_code(value)
            corp_code = await self._corp_code_for_stock(stock)
            if not corp_code:
                return None
        elif id_type == IdentifierType.VAT:
            biz = _normalize_biz_reg(value)
            corp_code = await self._corp_code_for_biz_reg(biz)
            if not corp_code:
                return None
        else:
            raise InvalidIdentifierError(
                f"KR adapter does not support identifier type {id_type}"
            )

        async with self._client() as client:
            resp = await get_with_retry(
                client,
                "/api/company.json",
                params={"crtfc_key": key, "corp_code": corp_code},
            )
            resp.raise_for_status()
            data = resp.json()

        status = str(data.get("status", ""))
        if status in _NO_DATA_STATUS:
            return None
        if status not in {"000", ""}:
            raise AdapterError(
                f"OpenDART company.json error status={status} message={data.get('message')}"
            )

        return _details_from_company(data, corp_code)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        key = self._require_key()
        corp_code = _normalize_corp_code(company_id)
        current_year = datetime.utcnow().year
        # OpenDART exposes fnlttSinglAcnt for the year *after* the fiscal year
        # ends, so newest published is current_year - 1 for most filers.
        target_years = list(range(current_year - 1, current_year - 1 - years, -1))

        filings: list[FinancialFiling] = []
        async with self._client() as client:
            list_resp = await get_with_retry(
                client,
                "/api/list.json",
                params={
                    "crtfc_key": key,
                    "corp_code": corp_code,
                    "bgn_de": f"{target_years[-1]}0101",
                    "end_de": f"{current_year}1231",
                    "pblntf_ty": "A",
                    "page_count": 100,
                },
            )
            list_resp.raise_for_status()
            list_payload = list_resp.json()
            list_status = str(list_payload.get("status", ""))
            list_items: list[dict[str, Any]] = []
            if list_status not in _NO_DATA_STATUS and list_status in {"000", ""}:
                list_items = list_payload.get("list") or []

            doc_urls: dict[int, str] = {}
            for item in list_items:
                rcept = item.get("rcept_no")
                rcept_dt = item.get("rcept_dt") or ""
                report_nm = (item.get("report_nm") or "").lower()
                if not rcept or len(rcept_dt) < 4:
                    continue
                # rcept_dt is the publication date; the fiscal year is the year
                # before for most annual report titles ("2023 사업보고서" filed 2024).
                m = re.search(r"(20\d{2})", item.get("report_nm") or "")
                if m:
                    yr = int(m.group(1))
                else:
                    try:
                        yr = int(rcept_dt[:4]) - 1
                    except ValueError:
                        continue
                if "사업보고서" not in (item.get("report_nm") or "") and "annual" not in report_nm:
                    # /api/list.json with pblntf_ty=A already filters to annual periodic
                    # reports, but report_nm sanity-checks it.
                    pass
                doc_urls.setdefault(
                    yr, f"{self.DART_VIEW_URL}?rcpNo={rcept}"
                )

            for year in target_years:
                items = await self._fetch_all_accounts(
                    client, key, corp_code, year, "11011", "CFS"
                )
                consolidated = True
                if not items:
                    # Fall back to parent-only (OFS) when no consolidated statements
                    # are filed — common for non-group filers.
                    items = await self._fetch_all_accounts(
                        client, key, corp_code, year, "11011", "OFS"
                    )
                    consolidated = False

                structured: dict[str, Any] | None = None
                currency: str = "KRW"
                if items:
                    structured, currency = _parse_fnltt_all_accounts(
                        items, year=year, consolidated=consolidated
                    )

                doc_url = doc_urls.get(year)
                if structured is None and not doc_url:
                    continue
                filings.append(
                    FinancialFiling(
                        company_id=corp_code,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency=currency or "KRW",
                        structured_data=structured,
                        document_url=doc_url,
                        document_format="json" if structured else "html",
                        source_url=(
                            f"https://dart.fss.or.kr/dsae001/selectPopup.ax?selectKey={corp_code}"
                        ),
                    )
                )

        filings.sort(key=lambda f: f.year, reverse=True)
        return filings

    async def _fetch_all_accounts(
        self,
        client: Any,
        key: str,
        corp_code: str,
        year: int,
        reprt_code: str,
        fs_div: str,
    ) -> list[dict[str, Any]]:
        """Call /api/fnlttSinglAcntAll.json and return list rows.

        Returns [] for "013" (no data). Raises AdapterError for "020" (quota)
        or other non-success statuses.
        """
        resp = await get_with_retry(
            client,
            "/api/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": key,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        status = str(payload.get("status", ""))
        if status in _NO_DATA_STATUS:
            return []
        if status in _QUOTA_STATUS:
            raise AdapterError(
                f"OpenDART quota exceeded (status=020): {payload.get('message')}"
            )
        if status not in {"000", ""}:
            raise AdapterError(
                f"OpenDART fnlttSinglAcntAll error status={status} "
                f"message={payload.get('message')}"
            )
        return payload.get("list") or []

    async def _corp_code_for_stock(self, stock_code: str) -> str | None:
        for r in await self._load_corp_codes():
            if r["stock_code"] == stock_code:
                return r["corp_code"]
        return None

    async def _corp_code_for_biz_reg(self, biz_reg: str) -> str | None:
        # OpenDART's company.json includes `bizr_no` in its payload but the
        # corp-code list (corpCode.xml) does not expose it. There's no public
        # OpenDART endpoint to reverse-lookup biz_reg → corp_code without
        # iterating every entity, so we can't resolve it cheaply.
        raise InvalidIdentifierError(
            "OpenDART does not support direct lookup by Business Registration "
            "Number. Use COMPANY_NUMBER (corp_code) or OTHER (stock code)."
        )


# OpenDART /api/fnlttSinglAcntAll.json returns rows tagged with `sj_div`
# (BS/IS/CIS/CF/SCE) and Korean `account_nm`. Where the filer uses the
# K-IFRS taxonomy the `account_id` carries an ifrs-full_* concept id too.
# We match by account_nm first (most reliable across filers) and fall back
# to concept_id when present.

# Balance sheet (sj_div = 'BS')
_BS_NM_MAP: dict[str, str] = {
    "자산총계": "total_assets",
    "유동자산": "current_assets",
    "비유동자산": "non_current_assets",
    "현금및현금성자산": "cash_and_equivalents",
    "재고자산": "inventories",
    "매출채권": "trade_receivables",
    "매출채권및기타채권": "trade_receivables",
    "부채총계": "total_liabilities",
    "유동부채": "current_liabilities",
    "비유동부채": "non_current_liabilities",
    "자본총계": "total_equity",
    "자본금": "share_capital",
    "이익잉여금": "retained_earnings",
    "이익잉여금(결손금)": "retained_earnings",
}

# Income statement (sj_div = 'IS' or 'CIS')
_IS_NM_MAP: dict[str, str] = {
    "매출액": "revenue",
    "수익(매출액)": "revenue",
    "영업수익": "revenue",
    "매출총이익": "gross_profit",
    "매출총이익(손실)": "gross_profit",
    "영업이익": "operating_profit",
    "영업이익(손실)": "operating_profit",
    "당기순이익": "net_income",
    "당기순이익(손실)": "net_income",
    "감가상각비": "depreciation_amortization",
    "이자비용": "interest_expense",
}

# Cash flow (sj_div = 'CF')
_CF_NM_MAP: dict[str, str] = {
    "영업활동현금흐름": "operating_cf",
    "영업활동으로인한현금흐름": "operating_cf",
    "투자활동현금흐름": "investing_cf",
    "투자활동으로인한현금흐름": "investing_cf",
    "재무활동현금흐름": "financing_cf",
    "재무활동으로인한현금흐름": "financing_cf",
}

# Fallback by ifrs-full concept id (account_id).
_CONCEPT_ID_MAP: dict[str, tuple[str, str]] = {
    "ifrs-full_Assets": ("balance_sheet", "total_assets"),
    "ifrs-full_CurrentAssets": ("balance_sheet", "current_assets"),
    "ifrs-full_NoncurrentAssets": ("balance_sheet", "non_current_assets"),
    "ifrs-full_CashAndCashEquivalents": ("balance_sheet", "cash_and_equivalents"),
    "ifrs-full_Inventories": ("balance_sheet", "inventories"),
    "ifrs-full_TradeAndOtherCurrentReceivables": ("balance_sheet", "trade_receivables"),
    "ifrs-full_Liabilities": ("balance_sheet", "total_liabilities"),
    "ifrs-full_CurrentLiabilities": ("balance_sheet", "current_liabilities"),
    "ifrs-full_NoncurrentLiabilities": ("balance_sheet", "non_current_liabilities"),
    "ifrs-full_Equity": ("balance_sheet", "total_equity"),
    "ifrs-full_IssuedCapital": ("balance_sheet", "share_capital"),
    "ifrs-full_RetainedEarnings": ("balance_sheet", "retained_earnings"),
    "ifrs-full_Revenue": ("income_statement", "revenue"),
    "ifrs-full_GrossProfit": ("income_statement", "gross_profit"),
    "dart_OperatingIncomeLoss": ("income_statement", "operating_profit"),
    "ifrs-full_ProfitLoss": ("income_statement", "net_income"),
    "ifrs-full_DepreciationAndAmortisationExpense": (
        "income_statement",
        "depreciation_amortization",
    ),
    "ifrs-full_InterestExpense": ("income_statement", "interest_expense"),
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": (
        "cash_flow",
        "operating_cf",
    ),
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": (
        "cash_flow",
        "investing_cf",
    ),
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": (
        "cash_flow",
        "financing_cf",
    ),
}

_SECTION_BY_SJ_DIV: dict[str, str] = {
    "BS": "balance_sheet",
    "IS": "income_statement",
    "CIS": "income_statement",
    "CF": "cash_flow",
}

_NM_MAP_BY_SECTION: dict[str, dict[str, str]] = {
    "balance_sheet": _BS_NM_MAP,
    "income_statement": _IS_NM_MAP,
    "cash_flow": _CF_NM_MAP,
}


def _parse_amount(raw: Any) -> float | None:
    """OpenDART amounts arrive as comma-separated strings; negatives as
    either '-123' or '(123)'. Returns None for blanks."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in {"", "-"}:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def _parse_fnltt_all_accounts(
    items: list[dict[str, Any]],
    year: int,
    consolidated: bool,
) -> tuple[dict[str, Any] | None, str]:
    """Parse /api/fnlttSinglAcntAll.json list rows into the canonical schema.

    All rows in `items` should already be one fs_div (CFS or OFS) because
    the endpoint is called with `fs_div` set. We still defensively filter.
    """
    if not items:
        return None, "KRW"

    fs_div_target = "CFS" if consolidated else "OFS"
    rows = [r for r in items if (r.get("fs_div") or fs_div_target) == fs_div_target]
    if not rows:
        rows = items

    balance_sheet: dict[str, float] = {}
    income_statement: dict[str, float] = {}
    cash_flow: dict[str, float] = {}
    raw_concepts: dict[str, float] = {}
    period_end_raw: str | None = None
    currency: str = "KRW"

    section_buckets: dict[str, dict[str, float]] = {
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
    }

    for entry in rows:
        name = (entry.get("account_nm") or "").strip()
        sj_div = (entry.get("sj_div") or "").strip().upper()
        concept_id = (entry.get("account_id") or "").strip()
        value = _parse_amount(entry.get("thstrm_amount"))
        if value is None:
            continue

        if name:
            raw_concepts.setdefault(name, value)

        cur = entry.get("currency")
        if cur:
            currency = str(cur).strip() or currency

        if not period_end_raw:
            period_end_raw = (entry.get("thstrm_dt") or "").strip() or None

        section = _SECTION_BY_SJ_DIV.get(sj_div)
        normalized: str | None = None
        if section and name:
            normalized = _NM_MAP_BY_SECTION[section].get(name)

        if not (section and normalized):
            # Fall back to ifrs concept_id when name match failed.
            mapped = _CONCEPT_ID_MAP.get(concept_id)
            if mapped:
                section, normalized = mapped

        if section and normalized:
            section_buckets[section].setdefault(normalized, value)

    period_end = _parse_period_end(period_end_raw, year)
    structured: dict[str, Any] = {
        "currency": currency or "KRW",
        "period_end": period_end.isoformat() if period_end else f"{year}-12-31",
        "consolidated": consolidated,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
        "raw_concepts": raw_concepts,
    }
    if not (balance_sheet or income_statement or cash_flow):
        return None, currency or "KRW"
    return structured, currency or "KRW"


def _parse_period_end(raw: str | None, fallback_year: int) -> date | None:
    """OpenDART `thstrm_dt` arrives like '제 55 기 (2023.12.31)' or
    '2023.12.31'. Extract the trailing yyyy.mm.dd."""
    if not raw:
        return None
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _details_from_company(data: dict[str, Any], corp_code: str) -> CompanyDetails:
    inc_date = _parse_yyyymmdd(data.get("est_dt"))
    addr = data.get("adres") or None
    biz_reg = (data.get("bizr_no") or "").strip()
    stock = (data.get("stock_code") or "").strip()

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=corp_code,
            label="OpenDART corp_code",
        ),
    ]
    if biz_reg:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=biz_reg,
                label="Business Registration Number",
            )
        )
    if stock:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.OTHER, value=stock, label="Stock code")
        )

    industry = (data.get("induty_code") or "").strip()
    return CompanyDetails(
        id=corp_code,
        name=(data.get("corp_name") or data.get("corp_name_eng") or "").strip(),
        country="KR",
        legal_form=data.get("corp_cls"),
        status="active",
        incorporation_date=inc_date,
        registered_address=addr,
        sic_codes=[industry] if industry else [],
        identifiers=identifiers,
        phone=data.get("phn_no"),
        website=data.get("hm_url") or None,
        email=data.get("em") or None,
        raw=data,
        source_url=(
            f"https://dart.fss.or.kr/dsae001/selectPopup.ax?selectKey={corp_code}"
        ),
    )


def _parse_yyyymmdd(s: str | None) -> date | None:
    if not s:
        return None
    cleaned = s.replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        return None
    try:
        return date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    except ValueError:
        return None
