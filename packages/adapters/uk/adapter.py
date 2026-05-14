"""UK adapter — Companies House REST API.

API docs: https://developer.company-information.service.gov.uk/
Auth:     HTTP Basic, username = API key, password empty.
Rate:     600 req / 5 minutes per key.
Free:     Yes, no payment.

Identifier: 8-character "Company Number". Normalize to upper, zero-padded.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_COMPANY_NUMBER_RE = re.compile(r"^[A-Z0-9]{1,10}$")


def _normalize_company_number(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "")
    if not _COMPANY_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(f"UK company number invalid: {value}")
    # Numeric numbers are zero-padded to 8 digits in the API.
    if cleaned.isdigit():
        cleaned = cleaned.zfill(8)
    return cleaned


class UKAdapter(CountryAdapter):
    country_code = "GB"
    country_name = "United Kingdom"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = "UK_COMPANIES_HOUSE_API_KEY"
    rate_limit_per_minute = 120

    BASE_URL = "https://api.company-information.service.gov.uk"
    DOC_BASE_URL = "https://document-api.company-information.service.gov.uk"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv(self.api_key_env)

    def _auth(self) -> httpx.BasicAuth | None:
        if not self.api_key:
            return None
        return httpx.BasicAuth(self.api_key, "")

    def _client(self, *, base_url: str | None = None) -> httpx.AsyncClient:
        return build_http_client(base_url=base_url or self.BASE_URL, auth=self._auth())

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
                resp = await get_with_retry(client, "/search/companies", params={"q": "tesco", "items_per_page": 1})
                if resp.status_code == 401:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        requires_api_key=True,
                        api_key_present=True,
                        notes="API key rejected.",
                    )
                resp.raise_for_status()
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
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                "/search/companies",
                params={"q": name, "items_per_page": limit},
            )
            resp.raise_for_status()
            items = resp.json().get("items", []) or []

        matches: list[CompanyMatch] = []
        for item in items[:limit]:
            cn = item.get("company_number")
            if not cn:
                continue
            matches.append(
                CompanyMatch(
                    id=cn,
                    name=item.get("title", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=cn,
                            label="Company Number",
                        )
                    ],
                    address=_address_from_snippet(item),
                    status=item.get("company_status"),
                    source_url=f"https://find-and-update.company-information.service.gov.uk/company/{cn}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(f"UK only supports COMPANY_NUMBER, got {id_type}")
        cn = _normalize_company_number(value)
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with self._client() as client:
            resp = await get_with_retry(client, f"/company/{cn}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

            officers: list[Director] = []
            try:
                off_resp = await get_with_retry(client, f"/company/{cn}/officers", params={"items_per_page": 25})
                if off_resp.status_code == 200:
                    officers = _parse_officers(off_resp.json())
            except Exception:
                officers = []

        return _details_from_company(data, officers)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        cn = _normalize_company_number(company_id)
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                f"/company/{cn}/filing-history",
                params={"category": "accounts", "items_per_page": 100},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            items = resp.json().get("items", []) or []

        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        for item in items:
            made_up_to = item.get("action_date") or item.get("date")
            if not made_up_to:
                continue
            try:
                period_end = date.fromisoformat(made_up_to[:10])
            except ValueError:
                continue
            if period_end.year < cutoff_year:
                continue
            doc_meta_url = (item.get("links") or {}).get("document_metadata")
            document_url = None
            if doc_meta_url:
                # The metadata link is on document-api; the human-readable PDF
                # is at metadata + "/content".
                document_url = f"{doc_meta_url}/content"
            filings.append(
                FinancialFiling(
                    company_id=cn,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="GBP",
                    structured_data=None,
                    document_url=document_url,
                    document_format="pdf",
                    source_url=(
                        f"https://find-and-update.company-information.service.gov.uk"
                        f"/company/{cn}/filing-history"
                    ),
                )
            )
        return filings


def _address_from_snippet(item: dict[str, Any]) -> str | None:
    addr = item.get("address_snippet")
    if addr:
        return addr
    a = item.get("address") or {}
    parts = [
        a.get("premises"),
        a.get("address_line_1"),
        a.get("address_line_2"),
        a.get("locality"),
        a.get("postal_code"),
        a.get("country"),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _parse_officers(payload: dict[str, Any]) -> list[Director]:
    directors: list[Director] = []
    for item in payload.get("items", []):
        appointed = item.get("appointed_on")
        resigned = item.get("resigned_on")
        try:
            appointed_d = date.fromisoformat(appointed) if appointed else None
        except ValueError:
            appointed_d = None
        try:
            resigned_d = date.fromisoformat(resigned) if resigned else None
        except ValueError:
            resigned_d = None
        directors.append(
            Director(
                name=item.get("name", "").strip(),
                role=item.get("officer_role"),
                appointed_on=appointed_d,
                resigned_on=resigned_d,
                nationality=item.get("nationality"),
            )
        )
    return directors


def _details_from_company(data: dict[str, Any], officers: list[Director]) -> CompanyDetails:
    inc = data.get("date_of_creation")
    diss = data.get("date_of_cessation")
    try:
        inc_date = date.fromisoformat(inc) if inc else None
    except ValueError:
        inc_date = None
    try:
        diss_date = date.fromisoformat(diss) if diss else None
    except ValueError:
        diss_date = None

    sic = data.get("sic_codes") or []
    cn = data.get("company_number")
    addr = data.get("registered_office_address") or {}
    addr_str = ", ".join(
        p for p in [
            addr.get("address_line_1"),
            addr.get("address_line_2"),
            addr.get("locality"),
            addr.get("region"),
            addr.get("postal_code"),
            addr.get("country"),
        ] if p
    ) or None

    return CompanyDetails(
        id=cn or "",
        name=data.get("company_name", ""),
        country="GB",
        legal_form=data.get("type"),
        status=data.get("company_status"),
        incorporation_date=inc_date,
        dissolution_date=diss_date,
        registered_address=addr_str,
        capital_amount=None,
        capital_currency="GBP",
        sic_codes=[str(s) for s in sic],
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=cn or "",
                label="Company Number",
            ),
        ],
        directors=officers,
        raw=data,
        source_url=f"https://find-and-update.company-information.service.gov.uk/company/{cn}",
    )
