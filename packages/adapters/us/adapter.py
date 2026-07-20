"""US adapter — SEC EDGAR (federal public company filings).

EDGAR provides:
- /cgi-bin/browse-edgar?action=getcompany  — search by name
- /submissions/CIK{10-digit}.json          — company submissions
- /api/xbrl/companyfacts/CIK{10-digit}.json — full structured XBRL facts

Free, no API key. SEC strongly requires a descriptive User-Agent with a
contact email; we set that here. Rate limit: 10 req/s globally.

Scope note: EDGAR only covers SEC-registered companies (largely public
issuers). State-registered LLCs are NOT here — those need state Secretary
of State scrapers, which are out of MVP scope.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime
from typing import Any

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

logger = logging.getLogger(__name__)

_CIK_RE = re.compile(r"^\d{1,10}$")


def _pad_cik(value: str) -> str:
    return value.strip().lstrip("0").zfill(10)


# Map normalized line items to the ordered list of US-GAAP concepts we
# accept. First non-null wins, so list the canonical tag before its
# common alternates.
_BALANCE_SHEET_CONCEPTS: dict[str, list[str]] = {
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "noncurrent_assets": ["AssetsNoncurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "noncurrent_liabilities": ["LiabilitiesNoncurrent"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
}

_INCOME_STATEMENT_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_sales": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_profit": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "depreciation_amortization": [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
    ],
    "interest_expense": ["InterestExpense"],
}

_CASH_FLOW_CONCEPTS: dict[str, list[str]] = {
    "operating_cf": ["NetCashProvidedByUsedInOperatingActivities"],
    "investing_cf": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing_cf": ["NetCashProvidedByUsedInFinancingActivities"],
}


class USAdapter(CountryAdapter):
    country_code = "US"
    country_name = "United States"
    identifier_types = [IdentifierType.CIK]
    primary_identifier = IdentifierType.CIK
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 600

    EDGAR_BASE = "https://www.sec.gov"
    DATA_BASE = "https://data.sec.gov"

    _tickers_cache: list[dict[str, Any]] | None = None
    # Per-CIK XBRL facts cache. Process-lifetime; Postgres-level caching is
    # handled by the route layer.
    _facts_cache: dict[str, dict[str, Any] | None] = {}
    _facts_lock = asyncio.Lock()

    def __init__(self) -> None:
        # SEC requires a descriptive UA with contact. Pulled from env so the
        # operator can customize.
        contact = os.getenv("SEC_EDGAR_USER_AGENT", "CreditLens dev contact@example.com")
        # NB: don't pin a Host header — different SEC subdomains are used.
        self._headers = {
            "User-Agent": contact,
            "Accept-Encoding": "gzip, deflate",
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(headers=self._headers) as client:
                resp = await get_with_retry(
                    client,
                    f"{self.EDGAR_BASE}/cgi-bin/browse-edgar",
                    params={"action": "getcompany", "company": "apple", "output": "atom"},
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
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="SEC EDGAR only — state-registered LLCs not covered.",
        )

    async def _load_tickers(self) -> list[dict[str, Any]]:
        """Cache the full SEC tickers file (one HTTP fetch per process)."""
        if USAdapter._tickers_cache is not None:
            return USAdapter._tickers_cache
        async with build_http_client(headers=self._headers) as client:
            resp = await get_with_retry(client, f"{self.EDGAR_BASE}/files/company_tickers.json")
            resp.raise_for_status()
            data = resp.json()
        # company_tickers.json is { "0": {...}, "1": {...}, ... }
        USAdapter._tickers_cache = list(data.values()) if isinstance(data, dict) else []
        return USAdapter._tickers_cache

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # Use the SEC's authoritative ticker→CIK file: simpler and more
        # reliable than parsing the EDGAR atom feed.
        rows = await self._load_tickers()
        needle = name.strip().lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for r in rows:
            title = str(r.get("title", "")).lower()
            if needle in title:
                # Prefer matches that start with the needle.
                score = 0 if title.startswith(needle) else 1
                scored.append((score, r))
        scored.sort(key=lambda x: x[0])
        out: list[CompanyMatch] = []
        for _, r in scored[:limit]:
            cik = _pad_cik(str(r.get("cik_str")))
            out.append(
                CompanyMatch(
                    id=cik,
                    name=str(r.get("title", "")),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.CIK, value=cik, label="CIK"),
                        *(
                            [RegistryIdentifier(type=IdentifierType.OTHER, value=str(r["ticker"]), label="Ticker")]
                            if r.get("ticker") else []
                        ),
                    ],
                    address=None,
                    status=None,
                    source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.CIK:
            raise InvalidIdentifierError("US adapter only supports CIK")
        if not _CIK_RE.match(value.strip()):
            raise InvalidIdentifierError(f"CIK invalid: {value}")
        cik = _pad_cik(value)
        async with build_http_client(headers=self._headers) as client:
            resp = await get_with_retry(client, f"{self.DATA_BASE}/submissions/CIK{cik}.json")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        inc_date = _parse_iso_date(data.get("formerNames", [{}])[0].get("from") if data.get("formerNames") else None)
        addresses = data.get("addresses") or {}
        biz = addresses.get("business") or {}
        addr_parts = [
            biz.get("street1"),
            biz.get("street2"),
            biz.get("city"),
            biz.get("stateOrCountry"),
            biz.get("zipCode"),
        ]
        addr = ", ".join(p for p in addr_parts if p) or None

        return CompanyDetails(
            id=cik,
            name=data.get("name", ""),
            country="US",
            legal_form=data.get("entityType"),
            status="active" if data.get("name") else None,
            incorporation_date=inc_date,
            registered_address=addr,
            sic_codes=[data["sic"]] if data.get("sic") else [],
            identifiers=[
                RegistryIdentifier(type=IdentifierType.CIK, value=cik, label="CIK"),
                *(
                    [RegistryIdentifier(type=IdentifierType.EIN, value=data["ein"], label="EIN")]
                    if data.get("ein") else []
                ),
            ],
            phone=biz.get("phone"),
            website=data.get("website"),
            raw={k: v for k, v in data.items() if k != "filings"},
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
        )

    async def _fetch_xbrl_facts(self, cik: str) -> dict[str, Any] | None:
        """Fetch and cache the SEC companyfacts JSON for one CIK.

        Returns None when the filer has no XBRL facts (404) — many small
        non-reporting registrants fall in this bucket.
        """
        padded = _pad_cik(cik)
        async with USAdapter._facts_lock:
            if padded in USAdapter._facts_cache:
                return USAdapter._facts_cache[padded]
        async with build_http_client(headers=self._headers) as client:
            resp = await get_with_retry(
                client, f"{self.DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json"
            )
        if resp.status_code == 404:
            USAdapter._facts_cache[padded] = None
            return None
        if resp.status_code >= 400:
            raise AdapterError(
                f"EDGAR companyfacts {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        USAdapter._facts_cache[padded] = data
        return data

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cik = _pad_cik(company_id)
        facts = await self._fetch_xbrl_facts(cik)
        if facts is None:
            return []

        async with build_http_client(headers=self._headers) as client:
            sub_resp = await get_with_retry(
                client, f"{self.DATA_BASE}/submissions/CIK{cik}.json"
            )
            submissions = sub_resp.json() if sub_resp.status_code == 200 else {}

        yearly = _build_structured_by_year(facts)

        doc_urls: dict[int, str] = {}
        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        # SEC submissions JSON calls the fiscal period column "reportDate"
        period_of_report = recent.get("reportDate") or []
        for form, acc, doc, period in zip(forms, accessions, primary_docs, period_of_report):
            if form != "10-K":
                continue
            try:
                yr = int(period[:4])
            except (ValueError, TypeError):
                continue
            acc_nodash = acc.replace("-", "")
            doc_urls.setdefault(
                yr,
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{doc}",
            )

        filings: list[FinancialFiling] = []
        cutoff = datetime.utcnow().year - years
        for year, structured in yearly.items():
            if year < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=cik,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=_parse_iso_date(structured.get("period_end"))
                    or date(year, 12, 31),
                    currency=structured.get("currency") or "USD",
                    structured_data=structured,
                    document_url=doc_urls.get(year),
                    document_format="xbrl",
                    source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _pick_fy_fact(
    block: dict[str, Any], year: int
) -> tuple[float | None, str | None]:
    """Return (value, end_date) for the best FY 10-K fact matching year.

    Preference order:
    1. fp == "FY", form == "10-K", end-year == year, latest `filed` (most
       recent restatement wins).
    2. Same as above but ignoring fp (some filers omit the period flag).
    """
    units = block.get("units") or {}
    unit_key = "USD" if "USD" in units else next(iter(units), None)
    if not unit_key:
        return None, None
    candidates: list[dict[str, Any]] = []
    relaxed: list[dict[str, Any]] = []
    for item in units[unit_key]:
        end = item.get("end")
        if not end:
            continue
        try:
            end_year = int(end[:4])
        except ValueError:
            continue
        if end_year != year or item.get("form") != "10-K":
            continue
        if item.get("fp") == "FY":
            candidates.append(item)
        else:
            relaxed.append(item)
    pool = candidates or relaxed
    if not pool:
        return None, None
    pool.sort(key=lambda x: (x.get("filed") or "", x.get("accn") or ""), reverse=True)
    best = pool[0]
    return best.get("val"), best.get("end")


def _all_fy_years(facts: dict[str, Any]) -> list[int]:
    """All distinct FY end-years observed in any us-gaap fact under 10-K."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    years: set[int] = set()
    for block in us_gaap.values():
        units = block.get("units") or {}
        for items in units.values():
            for item in items:
                if item.get("form") != "10-K":
                    continue
                end = item.get("end")
                if not end:
                    continue
                try:
                    years.add(int(end[:4]))
                except ValueError:
                    pass
    return sorted(years, reverse=True)


def _build_structured_by_year(facts: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Build the per-year structured_data payloads from companyfacts JSON.

    Output shape matches the ESEF parser so the risk engine can consume
    both interchangeably.
    """
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    out: dict[int, dict[str, Any]] = {}
    for year in _all_fy_years(facts):
        balance: dict[str, Any] = {}
        income: dict[str, Any] = {}
        cash_flow: dict[str, Any] = {}
        raw: dict[str, Any] = {}
        period_end: str | None = None

        def _extract(group: dict[str, Any], mapping: dict[str, list[str]]) -> None:
            nonlocal period_end
            for field, concepts in mapping.items():
                for concept in concepts:
                    block = us_gaap.get(concept)
                    if not block:
                        continue
                    val, end = _pick_fy_fact(block, year)
                    if val is None:
                        continue
                    group[field] = val
                    raw[concept] = val
                    if end and (period_end is None or end > period_end):
                        period_end = end
                    break

        _extract(balance, _BALANCE_SHEET_CONCEPTS)
        _extract(income, _INCOME_STATEMENT_CONCEPTS)
        _extract(cash_flow, _CASH_FLOW_CONCEPTS)

        # Synthesize gross profit when only revenue and cost of sales are
        # reported separately — the risk engine does the same, but having
        # it pre-computed is useful for inspection.
        if (
            "gross_profit" not in income
            and "revenue" in income
            and "cost_of_sales" in income
        ):
            income["gross_profit"] = income["revenue"] - income["cost_of_sales"]

        if not (balance or income or cash_flow):
            continue

        out[year] = {
            "currency": "USD",
            "period_end": period_end or f"{year}-12-31",
            "consolidated": True,
            "balance_sheet": balance,
            "income_statement": income,
            "cash_flow": cash_flow,
            "raw_concepts": raw,
        }
    return out
