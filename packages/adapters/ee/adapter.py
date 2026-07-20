"""Estonia adapter — e-Äriregister (Centre of Registers and Information Systems).

Three free, key-free public surfaces of the Estonian Business Register:

- Search + lookup: the Autocomplete JSON service
  ``https://ariregister.rik.ee/est/api/autocomplete`` — no contract, no auth.
  Matches both business names and registry codes, returning name, registrikood,
  status and legal address.
- Financials: the public company profile page lists every filed annual report
  (majandusaasta aruanne) with its fiscal year, period and a direct PDF
  download at ``/est/company/{regcode}/file/{fileId}``.

Detailed structured data and the XML services require a signed RIK contract and
are intentionally not used here.

Identifier: registry code (registrikood), 8 digits.
"""
from __future__ import annotations

import re
from datetime import date
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

_REGCODE_RE = re.compile(r"^\d{8}$")
_FISCAL_ROW_RE = re.compile(r'data-fiscal_year="(\d{4})"(.*?)</tr>', re.S)
_PERIOD_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4}) - (\d{2}\.\d{2}\.\d{4})")
_STATUS_RE = re.compile(r"<td>\s*(Kehtiv|Aegunud)\s*</td>")

_STATUS_LABELS = {"R": "active", "L": "liquidation", "N": "deleted", "K": "deleted"}


class EEAdapter(CountryAdapter):
    country_code = "EE"
    country_name = "Estonia"
    identifier_types = [IdentifierType.BUSINESS_ID]
    primary_identifier = IdentifierType.BUSINESS_ID
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://ariregister.rik.ee"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(
                    client, "/est/api/autocomplete", params={"q": "Bolt Technology"}
                )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code, name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            notes="Free e-Äriregister autocomplete + public annual-report PDFs.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._autocomplete(name)
        out: list[CompanyMatch] = []
        for r in rows[:limit]:
            reg_code = str(r.get("reg_code") or "").strip()
            if not reg_code:
                continue
            out.append(
                CompanyMatch(
                    id=reg_code,
                    name=(r.get("name") or "").strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.BUSINESS_ID, value=reg_code, label="Registrikood"
                        ),
                    ],
                    address=_address(r),
                    status=_STATUS_LABELS.get(r.get("status"), r.get("status")),
                    source_url=r.get("url") or f"{self.BASE_URL}/est/company/{reg_code}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.BUSINESS_ID:
            raise InvalidIdentifierError("EE only supports BUSINESS_ID (registrikood)")
        v = value.strip().replace(" ", "")
        if not _REGCODE_RE.match(v):
            raise InvalidIdentifierError(f"Estonian registrikood must be 8 digits: {value}")
        rows = await self._autocomplete(v)
        match = next((r for r in rows if str(r.get("reg_code")) == v), None)
        if match is None:
            return None
        return CompanyDetails(
            id=v,
            name=(match.get("name") or "").strip(),
            country="EE",
            status=_STATUS_LABELS.get(match.get("status"), match.get("status")),
            registered_address=_address(match),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.BUSINESS_ID, value=v, label="Registrikood"),
            ],
            raw=match,
            source_url=match.get("url") or f"{self.BASE_URL}/est/company/{v}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        v = company_id.strip().replace(" ", "")
        if not _REGCODE_RE.match(v):
            raise InvalidIdentifierError(f"Estonian registrikood must be 8 digits: {company_id}")
        page_url = f"{self.BASE_URL}/est/company/{v}"
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, f"/est/company/{v}")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            html = resp.text
        filings = _parse_annual_reports(html, v, page_url)
        return filings[:years]

    async def _autocomplete(self, query: str) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(
                client, "/est/api/autocomplete", params={"q": query}
            )
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("data") or []


def _address(row: dict[str, Any]) -> str | None:
    parts = [row.get("legal_address"), row.get("zip_code")]
    joined = ", ".join(str(p) for p in parts if p)
    return joined or None


def _parse_ddmmyyyy(s: str) -> date | None:
    try:
        d, m, y = (int(x) for x in s.split("."))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def _parse_annual_reports(
    html: str, reg_code: str, page_url: str
) -> list[FinancialFiling]:
    file_re = re.compile(rf"/est/company/{reg_code}/file/(\d+)(?!\?)")
    out: list[FinancialFiling] = []
    seen: set[int] = set()
    for row in _FISCAL_ROW_RE.finditer(html):
        year = int(row.group(1))
        if year in seen:
            continue
        body = row.group(2)
        period = _PERIOD_RE.search(body)
        period_end = _parse_ddmmyyyy(period.group(2)) if period else None
        file_match = file_re.search(body)
        if file_match is None:
            continue
        document_url = (
            f"https://ariregister.rik.ee/est/company/{reg_code}/file/{file_match.group(1)}"
        )
        seen.add(year)
        out.append(
            FinancialFiling(
                company_id=reg_code,
                year=year,
                type=FilingType.ANNUAL_REPORT,
                period_end=period_end,
                currency="EUR" if year >= 2011 else None,
                document_url=document_url,
                document_format="pdf",
                source_url=page_url,
            )
        )
    out.sort(key=lambda f: f.year, reverse=True)
    return out
