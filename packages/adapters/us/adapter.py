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

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cik = _pad_cik(company_id)
        async with build_http_client(headers=self._headers) as client:
            resp = await get_with_retry(client, f"{self.DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json")
            if resp.status_code == 404:
                return []
            if resp.status_code >= 400:
                raise AdapterError(f"EDGAR companyfacts {resp.status_code}: {resp.text[:200]}")
            facts = resp.json()

            sub_resp = await get_with_retry(client, f"{self.DATA_BASE}/submissions/CIK{cik}.json")
            submissions = sub_resp.json() if sub_resp.status_code == 200 else {}

        annual_per_year = _flatten_xbrl_to_yearly(facts)

        # Build a document_url map from the recent submissions list (10-K only).
        doc_urls: dict[int, str] = {}
        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        period_of_report = recent.get("periodOfReport") or []
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
        for year, structured in annual_per_year.items():
            if year < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=cik,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="USD",
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


# Mapping from SEC US-GAAP XBRL tags to our normalized line items.
_XBRL_TAG_MAP: dict[str, str] = {
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "CostOfRevenue": "cost_of_sales",
    "CostOfGoodsAndServicesSold": "cost_of_sales",
    "GrossProfit": "gross_profit",
    "OperatingIncomeLoss": "operating_profit",
    "NetIncomeLoss": "net_income",
    "Assets": "total_assets",
    "AssetsCurrent": "current_assets",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "InventoryNet": "inventory",
    "AccountsReceivableNetCurrent": "receivables",
    "Liabilities": "total_liabilities",
    "LiabilitiesCurrent": "current_liabilities",
    "LongTermDebt": "long_term_debt",
    "StockholdersEquity": "equity",
    "RetainedEarningsAccumulatedDeficit": "retained_earnings",
}


def _flatten_xbrl_to_yearly(facts: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Reduce SEC companyfacts JSON to {year: {line: value}} for FY filings."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    out: dict[int, dict[str, Any]] = {}
    for tag, normalized in _XBRL_TAG_MAP.items():
        block = us_gaap.get(tag)
        if not block:
            continue
        units = block.get("units") or {}
        # Prefer USD, fall back to first available unit.
        unit_key = "USD" if "USD" in units else (next(iter(units), None) if units else None)
        if not unit_key:
            continue
        for item in units[unit_key]:
            if item.get("form") != "10-K":
                continue
            if item.get("fp") not in (None, "FY"):
                continue
            end = item.get("end")
            if not end:
                continue
            try:
                year = int(end[:4])
            except ValueError:
                continue
            year_block = out.setdefault(year, {})
            # Keep the highest-quality value: 10-K FY, prefer fy == year.
            year_block.setdefault(normalized, item.get("val"))
    return out
