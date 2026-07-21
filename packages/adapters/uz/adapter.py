"""Uzbekistan adapter — openinfo.uz corporate disclosure portal.

Source: **openinfo.uz** — the Single Portal of Corporate Information run by
the Center for Coordination and Development of the Securities Market. It is
the official disclosure venue where Uzbek joint-stock companies, banks and
insurers file their annual reports and financial statements. Its backend
(``new-api.openinfo.uz``) is an unauthenticated Django REST API:

* ``/api/v2/organizations/organizations/?search=<q>`` — legal-entity search
  by name or INN, returning INN, names, address, OKED/OKONX, ticker,
  director, listing status, contact details.
* ``/api/v2/reports/{jsc,bank,insurance}/annual/`` — filed annual reports.
  A report detail carries the actual filed balance-sheet and
  financial-results line items plus the auditor's conclusion PDF.

All three capabilities resolve real, filed data with no API key. Coverage is
the population of disclosing entities (listed issuers, JSCs, banks, insurers)
— the only Uzbek dataset that exposes structured filings for free. The full
350k-entity registry lives at stat.uz / orginfo.uz (HTML only) and can be
wired in later for broader name → INN resolution.

Identifier:
- VAT → INN ("STIR" in Uzbek; "ИНН" in Russian) — 9 digits assigned by the
  State Tax Committee. Same number serves as the VAT registration and the
  legal-entity tax ID.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import quote

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

logger = logging.getLogger(__name__)

_INN_RE = re.compile(r"^\d{9}$")

_API_BASE = "https://new-api.openinfo.uz"
_SITE_BASE = "https://openinfo.uz"
_MEDIA_BASE = "https://openinfo.uz/media/"

_ANNUAL_REPORT_CATEGORIES = ("jsc/annual", "bank/annual", "insurance/annual")

_ROW_FIELDS = ("title", "tnum", "value", "value1", "value2", "is_title", "is_highlight")


def _normalize_inn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("UZ"):
        cleaned = cleaned[2:]
    if not _INN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Uzbekistan INN must be exactly 9 digits, got: {value}"
        )
    return cleaned


def _legal_form(org: dict) -> str | None:
    short = (org.get("short_name_text") or "").strip()
    tokens = short.replace('"', " ").split()
    if tokens and tokens[-1].isupper() and len(tokens[-1]) <= 6:
        return tokens[-1]
    return None


def _status_label(org: dict) -> str | None:
    stat = org.get("status_from_stat_uz")
    if stat:
        return str(stat)
    if org.get("status") is True:
        return "active"
    if org.get("status") is False:
        return "inactive"
    return None


def _clean_rows(rows: list | None) -> list[dict] | None:
    if not rows:
        return None
    return [{k: r.get(k) for k in _ROW_FIELDS if k in r} for r in rows]


class UZAdapter(CountryAdapter):
    country_code = "UZ"
    country_name = "Uzbekistan"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    def _client(self):
        return build_http_client(
            base_url=_API_BASE,
            headers={
                "Accept": "application/json",
                "Accept-Language": "en,uz;q=0.7,ru;q=0.5",
            },
            timeout=30.0,
        )

    async def _get_json(self, client, path: str) -> dict | None:
        resp = await get_with_retry(client, path)
        if resp.status_code != 200:
            return None
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype:
            return None
        return resp.json()

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                data = await self._get_json(client, "/api/v2/reports/")
            ok = isinstance(data, dict) and "jsc/annual" in data
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"openinfo.uz probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "openinfo.uz disclosure portal reachable. Coverage is the "
                "population of disclosing entities (JSCs, banks, insurers)."
            ),
        )

    def _to_match(self, org: dict) -> CompanyMatch:
        inn = str(org["inn"])
        name = org.get("full_name_text") or org.get("short_name_text") or inn
        return CompanyMatch(
            id=inn,
            name=name,
            country="UZ",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=inn, label="INN/STIR")
            ],
            address=org.get("location") or org.get("address"),
            status=_status_label(org),
            source_url=f"{_SITE_BASE}/en/organizations/{org['id']}",
        )

    def _to_details(self, org: dict) -> CompanyDetails:
        inn = str(org["inn"])
        detailinfo = org.get("detailinfo") or {}
        directors: list[Director] = []
        if detailinfo.get("director_name") and detailinfo["director_name"] != "-":
            directors.append(Director(name=detailinfo["director_name"], role="Director"))
        if detailinfo.get("accountant_name"):
            directors.append(
                Director(name=detailinfo["accountant_name"], role="Chief Accountant")
            )

        identifiers = [
            RegistryIdentifier(type=IdentifierType.VAT, value=inn, label="INN/STIR")
        ]
        if org.get("okpo"):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.OTHER, value=str(org["okpo"]), label="OKPO"
                )
            )
        if org.get("gov_reg_number"):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=str(org["gov_reg_number"]),
                    label="State registration number",
                )
            )

        incorporation: date | None = None
        for key in ("gov_registration_date", "registration_date", "primary_listing_date"):
            raw = org.get(key)
            if isinstance(raw, str) and len(raw) >= 10:
                try:
                    incorporation = date.fromisoformat(raw[:10])
                    break
                except ValueError:
                    continue

        website = org.get("web_site") or None
        if website and not website.startswith("http"):
            website = f"https://{website}"

        return CompanyDetails(
            id=inn,
            name=org.get("full_name_text") or org.get("short_name_text") or inn,
            country="UZ",
            legal_form=_legal_form(org),
            status=_status_label(org),
            incorporation_date=incorporation,
            registered_address=org.get("location") or org.get("address"),
            sic_codes=[str(org["okonx"])] if org.get("okonx") else [],
            nace_codes=[str(org["oked"])] if org.get("oked") else [],
            identifiers=identifiers,
            directors=directors,
            website=website,
            phone=detailinfo.get("phone_number") or None,
            email=org.get("email") or None,
            raw=org,
            source_url=f"{_SITE_BASE}/en/organizations/{org['id']}",
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        async with self._client() as client:
            data = await self._get_json(
                client,
                f"/api/v2/organizations/organizations/"
                f"?search={quote(name)}&page_size={max(limit, 10)}",
            )
        results = (data or {}).get("results") or []
        return [self._to_match(o) for o in results[:limit] if o.get("inn")]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Uzbekistan adapter only supports VAT (INN) or "
                f"COMPANY_NUMBER, got {id_type}"
            )
        inn = _normalize_inn(value)
        async with self._client() as client:
            data = await self._get_json(
                client,
                f"/api/v2/organizations/organizations/?search={inn}&page_size=20",
            )
            results = (data or {}).get("results") or []
            match = next((o for o in results if str(o.get("inn")) == inn), None)
            if match is None:
                return None
            detail = await self._get_json(
                client,
                f"/api/v2/organizations/organizations/{match['id']}/",
            )
        return self._to_details(detail if isinstance(detail, dict) else match)

    async def _financials_for_category(
        self, client, category: str, inn: str, years: int
    ) -> list[FinancialFiling]:
        listing = await self._get_json(
            client, f"/api/v2/reports/{category}/?search={inn}"
        )
        stubs = (listing or {}).get("results") or []
        if not stubs:
            return []

        by_year: dict[int, FinancialFiling] = {}
        for stub in stubs[: years + 5]:
            detail = await self._get_json(
                client, f"/api/v2/reports/{category}/{stub['id']}/"
            )
            if not isinstance(detail, dict):
                continue
            org = detail.get("organization") or {}
            detail_inn = str(detail.get("organization_inn") or org.get("inn") or "")
            if detail_inn != inn:
                continue
            reporting_year = detail.get("reporting_year")
            if not isinstance(reporting_year, str) or len(reporting_year) < 4:
                continue
            year = int(reporting_year[:4])
            if year in by_year:
                continue
            by_year[year] = self._build_filing(
                inn, category, stub["id"], detail, reporting_year
            )

        ordered = [by_year[y] for y in sorted(by_year, reverse=True)]
        return ordered[:years]

    def _build_filing(
        self, inn: str, category: str, report_id: int, detail: dict, reporting_year: str
    ) -> FinancialFiling:
        period_end: date | None = None
        try:
            period_end = date.fromisoformat(reporting_year[:10])
        except ValueError:
            pass

        structured: dict[str, list[dict]] = {}
        for key, label in (
            ("balance_sheet_report", "balance_sheet"),
            ("financial_results_report", "financial_results"),
            ("annual_activity_report", "activity_ratios"),
        ):
            rows = _clean_rows(detail.get(key))
            if rows:
                structured[label] = rows

        document_url: str | None = None
        document_format: str | None = None
        for audit in detail.get("audition_result_report") or []:
            conclusion = audit.get("conclusion_file")
            if conclusion:
                document_url = _MEDIA_BASE + quote(conclusion, safe="/")
                document_format = "pdf"
                break

        return FinancialFiling(
            company_id=inn,
            year=int(reporting_year[:4]),
            type=FilingType.ANNUAL_REPORT,
            period_end=period_end,
            currency="UZS",
            structured_data=structured or None,
            document_url=document_url,
            document_format=document_format,
            source_url=f"{_SITE_BASE}/en/reports/{category}/{report_id}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        inn = _normalize_inn(company_id)
        async with self._client() as client:
            for category in _ANNUAL_REPORT_CATEGORIES:
                filings = await self._financials_for_category(
                    client, category, inn, years
                )
                if filings:
                    return filings
        return []
