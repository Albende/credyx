"""Taiwan adapter — GCIS open data (Ministry of Economic Affairs).

Free OData JSON datasets at https://data.gcis.nat.gov.tw/od/.
No auth. We throttle to 60/min to stay polite.

Identifier: 統一編號 (Unified Business Number, UBN), 8 digits. Serves as both
the tax ID and the company-registry ID, so we expose it as `IdentifierType.VAT`.

Financials are best-effort: MOPS (twse.com.tw) hosts XBRL for *listed* firms
behind an interactive HTML form, so we synthesize the canonical filing URL per
year and return it for caller fetching. Unlisted Taiwanese companies have no
free financial source — we return [] in that case.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
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
    # GCIS OData datasets. Only Business_Accounting_NO is filterable on either;
    # name-based search is not supported by the free open-data layer.
    COMPANY_DATASET = "6BBA2268-1367-4B42-9CCA-BC17499EBE8C"
    COMPANY_DETAIL_DATASET = "5F64D864-61CB-4D0D-8AD9-492047CC1EA6"
    MOPS_FILING_URL = (
        "https://mopsfin.twse.com.tw/server-java/t164sb01"
        "?step=1&CO_ID={ubn}&SYEAR={year}&SSEASON=4&REPORT_ID=C"
    )
    GCIS_COMPANY_PAGE = "https://findbiz.nat.gov.tw/fts/query/QueryBar/queryInit.do?keyword={ubn}"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.GCIS_BASE) as client:
                resp = await get_with_retry(
                    client,
                    f"/{self.COMPANY_DATASET}",
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
            notes="Registry via GCIS ✅. Financials best-effort: MOPS XBRL for listed firms only.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # The GCIS open-data OData endpoints only allow filtering on the
        # primary key (Business_Accounting_NO) — free-text Company_Name search
        # is not supported there, and findbiz.nat.gov.tw blocks programmatic
        # access. We therefore accept a UBN here and route it to a real lookup;
        # arbitrary names raise NotImplemented so callers can't be misled by an
        # always-empty result.
        cleaned = name.strip().replace(" ", "").replace("-", "")
        if not _UBN_RE.match(cleaned):
            raise AdapterNotImplementedError(
                "TW free-text name search is unavailable on free GCIS OData. "
                "Pass an 8-digit UBN, or use OpenCorporates/GLEIF as a fallback."
            )
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

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.VAT:
            raise InvalidIdentifierError(f"TW only supports VAT (UBN), got {id_type}")
        ubn = _normalize_ubn(value)
        params = {
            "$format": "json",
            "$filter": f"Business_Accounting_NO eq '{ubn}'",
            "$top": "1",
        }
        # Prefer the detailed dataset; fall back to the basic one if empty.
        rows = await self._gcis_query(self.COMPANY_DETAIL_DATASET, params)
        if not rows:
            rows = await self._gcis_query(self.COMPANY_DATASET, params)
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
        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        # MOPS publishes annual reports for the previous fiscal year; check the
        # last `years` years. We probe with a HEAD-ish GET and only keep URLs
        # that actually return 200 with non-empty content — never invent.
        async with build_http_client(timeout=15.0) as client:
            for year in range(current_year - years, current_year):
                url = self.MOPS_FILING_URL.format(ubn=ubn, year=year)
                try:
                    resp = await client.get(url)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code != 200:
                    continue
                body = resp.text or ""
                # MOPS returns an HTML page even for "no data"; require a known
                # filing-link marker to consider the year covered.
                if "REPORT_ID" not in body and "FileName" not in body and ".pdf" not in body.lower():
                    continue
                filings.append(
                    FinancialFiling(
                        company_id=ubn,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="TWD",
                        document_url=url,
                        document_format="html",
                        source_url=(
                            "https://mops.twse.com.tw/mops/web/index"
                        ),
                    )
                )
        return filings

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
        return _coerce_gcis_rows(payload)


def _coerce_gcis_rows(payload: Any) -> list[dict[str, Any]]:
    # GCIS sometimes returns a bare list, sometimes a dict with an error code,
    # sometimes an OData envelope. Normalize all three.
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            return [r for r in payload["value"] if isinstance(r, dict)]
        if isinstance(payload.get("data"), list):
            return [r for r in payload["data"] if isinstance(r, dict)]
    return []


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


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
