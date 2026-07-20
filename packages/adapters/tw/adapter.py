"""Taiwan adapter — GCIS registry (MOEA) + TWSE OpenAPI financials.

Two free, key-free government sources:

* **Registry** — GCIS open data (Ministry of Economic Affairs) OData JSON at
  ``https://data.gcis.nat.gov.tw/od/data/api/``. Lookup filters on the
  Unified Business Number (統一編號, UBN); the keyword dataset supports
  fuzzy ``Company_Name like`` search on active companies.
* **Financials** — TWSE OpenAPI (``https://openapi.twse.com.tw/v1``). The
  Taiwan Stock Exchange publishes structured balance-sheet and
  income-statement figures for every *listed* company as plain JSON. We map
  UBN → stock code via the listed-company master file, then pull the latest
  filed statements. Unlisted companies have no free structured financial
  source, so ``fetch_financials`` returns ``[]`` for them.

Identifier: 統一編號 (UBN), 8 digits. Serves as both the tax ID and the
company-registry ID, so we expose it as ``IdentifierType.VAT``.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

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

_UBN_RE = re.compile(r"^\d{8}$")

# UBN checksum weights per the MoF spec.
_UBN_WEIGHTS = (1, 2, 1, 2, 1, 2, 4, 1)


def _normalize_ubn(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _UBN_RE.match(cleaned):
        raise InvalidIdentifierError(f"Taiwan UBN must be 8 digits: {value}")
    if not _validate_ubn_checksum(cleaned):
        raise InvalidIdentifierError(f"Taiwan UBN checksum invalid: {value}")
    return cleaned


def _validate_ubn_checksum(ubn: str) -> bool:
    # Each digit*weight is reduced to its digit-sum. After the MoF's 2023
    # relaxation (UBN exhaustion), residue 0 *or* 9 is accepted universally;
    # before that, residue 9 was only valid when the 7th digit was 7.
    digits = [int(c) for c in ubn]
    products = []
    for d, w in zip(digits, _UBN_WEIGHTS):
        prod = d * w
        products.append((prod // 10) + (prod % 10))
    total = sum(products)
    return total % 10 == 0 or total % 10 == 9


class TWAdapter(CountryAdapter):
    country_code = "TW"
    country_name = "Taiwan"
    identifier_types = [IdentifierType.VAT]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 60

    GCIS_BASE = "https://data.gcis.nat.gov.tw/od/data/api"
    # Detail dataset (公司登記基本資料-應用一): full record, filterable only on
    # Business_Accounting_NO.
    COMPANY_DETAIL_DATASET = "5F64D864-61CB-4D0D-8AD9-492047CC1EA6"
    # Keyword dataset (公司登記關鍵字查詢): supports
    # ``Company_Name like {kw} and Company_Status eq {code}`` fuzzy search.
    COMPANY_KEYWORD_DATASET = "6BBA2268-1367-4B42-9CCA-BC17499EBE8C"
    # GCIS status code 01 = 核准設立 (approved / active).
    _ACTIVE_STATUS_CODE = "01"

    GCIS_COMPANY_PAGE = (
        "https://findbiz.nat.gov.tw/fts/query/QueryBar/queryInit.do?keyword={ubn}"
    )

    # TWSE OpenAPI — free, key-free structured filings for listed companies.
    TWSE_BASE = "https://openapi.twse.com.tw/v1"
    TWSE_LISTED_MASTER = "opendata/t187ap03_L"
    # Income-statement / balance-sheet datasets, one pair per industry taxonomy
    # (ci = general, basi = banks, bd = securities, fh = financial holding,
    # ins = insurers, mim = other financial). We probe them in order until the
    # company's stock code is found.
    TWSE_INCOME_DATASETS = tuple(
        f"opendata/t187ap06_L_{suf}" for suf in ("ci", "basi", "bd", "fh", "ins", "mim")
    )
    TWSE_BALANCE_DATASETS = tuple(
        f"opendata/t187ap07_L_{suf}" for suf in ("ci", "basi", "bd", "fh", "ins", "mim")
    )
    MOPS_COMPANY_PAGE = "https://mops.twse.com.tw/mops/web/t05st03?firstin=1&co_id={stock}"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.GCIS_BASE) as client:
                resp = await get_with_retry(
                    client,
                    f"/{self.COMPANY_DETAIL_DATASET}",
                    params={
                        "$format": "json",
                        "$filter": "Business_Accounting_NO eq '22099131'",
                        "$top": "1",
                    },
                )
                resp.raise_for_status()
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
                "Registry via GCIS ✅. Financials via TWSE OpenAPI for listed "
                "firms; unlisted return []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # An 8-digit input is a UBN — route it straight to a precise lookup.
        cleaned = name.strip().replace(" ", "").replace("-", "")
        if _UBN_RE.match(cleaned):
            details = await self.lookup_by_identifier(IdentifierType.VAT, cleaned)
            if details is None:
                return []
            return [
                CompanyMatch(
                    id=details.id,
                    name=details.name,
                    country=self.country_code,
                    identifiers=details.identifiers,
                    address=details.registered_address,
                    status=details.status,
                    source_url=details.source_url,
                )
            ][:limit]

        keyword = name.strip()
        if not keyword:
            return []
        # The keyword dataset requires both the fuzzy name and an explicit
        # Company_Status; 01 = active. GCIS matches on the registered Chinese
        # name only — Latin-script queries won't match registry records.
        rows = await self._gcis_query(
            self.COMPANY_KEYWORD_DATASET,
            {
                "$format": "json",
                "$filter": (
                    f"Company_Name like {keyword} "
                    f"and Company_Status eq {self._ACTIVE_STATUS_CODE}"
                ),
                "$skip": "0",
                "$top": str(max(1, limit)),
            },
        )
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            ubn = (r.get("Business_Accounting_NO") or "").strip()
            if not ubn:
                continue
            matches.append(
                CompanyMatch(
                    id=ubn,
                    name=(r.get("Company_Name") or "").strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT, value=ubn, label="UBN"
                        )
                    ],
                    address=r.get("Company_Location") or None,
                    status=_status_from_state(
                        r.get("Company_Status_Desc") or r.get("Company_Status")
                    ),
                    source_url=self.GCIS_COMPANY_PAGE.format(ubn=ubn),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.VAT:
            raise InvalidIdentifierError(f"TW only supports VAT (UBN), got {id_type}")
        ubn = _normalize_ubn(value)
        rows = await self._gcis_query(
            self.COMPANY_DETAIL_DATASET,
            {
                "$format": "json",
                "$filter": f"Business_Accounting_NO eq '{ubn}'",
                "$top": "1",
            },
        )
        if not rows:
            return None
        r = rows[0]
        capital = _coerce_float(
            r.get("Capital_Stock_Amount")
            or r.get("Paid_In_Capital_Amount")
            or r.get("Capital_Amount")
        )
        return CompanyDetails(
            id=ubn,
            name=(r.get("Company_Name") or "").strip(),
            country="TW",
            legal_form=r.get("Company_Type_Desc") or r.get("Company_Type"),
            status=_status_from_state(
                r.get("Company_Status_Desc") or r.get("Company_Status")
            ),
            incorporation_date=_parse_roc_or_iso_date(
                r.get("Company_Setup_Date") or r.get("Setup_Date")
            ),
            registered_address=r.get("Company_Location") or None,
            capital_amount=capital,
            capital_currency="TWD",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=ubn, label="UBN"),
            ],
            raw=r,
            source_url=self.GCIS_COMPANY_PAGE.format(ubn=ubn),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ubn = _normalize_ubn(company_id)
        listed = await self._listed_record_for_ubn(ubn)
        if listed is None:
            # Not a TWSE-listed company: no free structured financial source.
            return []
        stock = listed["公司代號"].strip()

        income_row, income_src = await self._first_row_for_stock(
            self.TWSE_INCOME_DATASETS, stock
        )
        balance_row, balance_src = await self._first_row_for_stock(
            self.TWSE_BALANCE_DATASETS, stock
        )
        if income_row is None and balance_row is None:
            return []

        anchor = income_row or balance_row
        year = _roc_year_to_gregorian(anchor.get("年度"))
        quarter = _coerce_int(anchor.get("季別")) or 4
        if year is None:
            return []
        period_end = _quarter_end(year, quarter)

        structured = _build_structured(
            balance_row, income_row, year=year, quarter=quarter, period_end=period_end
        )
        return [
            FinancialFiling(
                company_id=ubn,
                year=year,
                type=(
                    FilingType.ANNUAL_REPORT
                    if quarter == 4
                    else FilingType.BALANCE_SHEET
                ),
                period_end=period_end,
                currency="TWD",
                structured_data=structured,
                document_format="json",
                source_url=f"{self.TWSE_BASE}/{income_src or balance_src}",
            )
        ]

    async def _listed_record_for_ubn(self, ubn: str) -> dict[str, Any] | None:
        rows = await self._twse_query(self.TWSE_LISTED_MASTER)
        for r in rows:
            if (r.get("營利事業統一編號") or "").strip() == ubn:
                return r
        return None

    async def _first_row_for_stock(
        self, datasets: tuple[str, ...], stock: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        for dataset in datasets:
            rows = await self._twse_query(dataset)
            for r in rows:
                if (r.get("公司代號") or "").strip() == stock:
                    return r, dataset
        return None, None

    async def _gcis_query(
        self, dataset_id: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.GCIS_BASE) as client:
            resp = await get_with_retry(client, f"/{dataset_id}", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                return []
        return _coerce_rows(payload)

    async def _twse_query(self, dataset: str) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.TWSE_BASE) as client:
            resp = await get_with_retry(
                client, f"/{dataset}", headers={"Accept": "application/json"}
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                return []
        return _coerce_rows(payload)


def _coerce_rows(payload: Any) -> list[dict[str, Any]]:
    # Sources return a bare list (TWSE, GCIS success), an OData envelope, or a
    # dict with an error code. Normalize all shapes.
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            return [r for r in payload["value"] if isinstance(r, dict)]
        if isinstance(payload.get("data"), list):
            return [r for r in payload["data"] if isinstance(r, dict)]
    return []


# TWSE statement field → canonical key. Amounts are in thousands of TWD.
_BALANCE_FIELD_MAP: dict[str, str] = {
    "流動資產": "current_assets",
    "非流動資產": "non_current_assets",
    "資產總額": "total_assets",
    "流動負債": "current_liabilities",
    "非流動負債": "non_current_liabilities",
    "負債總額": "total_liabilities",
    "股本": "share_capital",
    "資本公積": "capital_surplus",
    "保留盈餘": "retained_earnings",
    "權益總額": "total_equity",
    "歸屬於母公司業主之權益合計": "equity_attributable_to_owners",
}

_INCOME_FIELD_MAP: dict[str, str] = {
    "營業收入": "revenue",
    "利息淨收益": "revenue",
    "營業成本": "cost_of_sales",
    "營業毛利（毛損）淨額": "gross_profit",
    "營業毛利（毛損）": "gross_profit",
    "營業費用": "operating_expenses",
    "營業利益（損失）": "operating_profit",
    "稅前淨利（淨損）": "profit_before_tax",
    "所得稅費用（利益）": "income_tax",
    "本期淨利（淨損）": "net_income",
    "淨利（淨損）歸屬於母公司業主": "net_income_attributable_to_owners",
    "基本每股盈餘（元）": "eps_basic",
}


def _build_structured(
    balance_row: dict[str, Any] | None,
    income_row: dict[str, Any] | None,
    *,
    year: int,
    quarter: int,
    period_end: date,
) -> dict[str, Any]:
    balance_sheet = _map_statement(balance_row, _BALANCE_FIELD_MAP)
    income_statement = _map_statement(income_row, _INCOME_FIELD_MAP)
    raw_concepts: dict[str, float] = {}
    for row in (balance_row, income_row):
        for name, value in _numeric_items(row):
            raw_concepts.setdefault(name, value)
    return {
        "currency": "TWD",
        "unit": "thousands",
        "period_end": period_end.isoformat(),
        "quarter": quarter,
        "consolidated": True,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "raw_concepts": raw_concepts,
    }


def _map_statement(
    row: dict[str, Any] | None, field_map: dict[str, str]
) -> dict[str, float]:
    if not row:
        return {}
    out: dict[str, float] = {}
    for field, key in field_map.items():
        value = _coerce_float(row.get(field))
        if value is not None:
            out.setdefault(key, value)
    return out


def _numeric_items(row: dict[str, Any] | None) -> list[tuple[str, float]]:
    if not row:
        return []
    skip = {"出表日期", "年度", "季別", "公司代號", "公司名稱"}
    items: list[tuple[str, float]] = []
    for name, raw in row.items():
        if name in skip:
            continue
        value = _coerce_float(raw)
        if value is not None:
            items.append((name, value))
    return items


def _status_from_state(state: Any) -> str | None:
    if not state:
        return None
    s = str(state)
    if any(tok in s for tok in ("核准設立", "核准", "營業中", "Active", "active")):
        return "active"
    if any(tok in s for tok in ("解散", "撤銷", "廢止", "歇業", "Dissolved", "dissolved")):
        return "ceased"
    return s


def _parse_roc_or_iso_date(s: Any) -> date | None:
    # GCIS dates appear as either ISO ("2020-04-01"), ROC years ("0950101"), or
    # compact "20200401". Try the common shapes and give up if none match.
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    if len(digits) == 7:
        try:
            roc_year = int(digits[:3])
            return date(roc_year + 1911, int(digits[3:5]), int(digits[5:7]))
        except ValueError:
            return None
    return None


def _roc_year_to_gregorian(raw: Any) -> int | None:
    n = _coerce_int(raw)
    if n is None:
        return None
    # TWSE reports the ROC year (e.g. 115); Gregorian = ROC + 1911.
    return n + 1911 if n < 1000 else n


def _quarter_end(year: int, quarter: int) -> date:
    month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}.get(quarter, (12, 31))
    return date(year, month_day[0], month_day[1])


def _coerce_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
