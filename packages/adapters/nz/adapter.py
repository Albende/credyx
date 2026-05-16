"""New Zealand adapter — NZBN Register (Companies Office / MBIE).

API docs: https://api.business.govt.nz/api-portal/
Auth:     HTTP header `Ocp-Apim-Subscription-Key: {key}` (free, instant signup).
Rate:     100 req/min default. We throttle to 90.

Identifiers:
- NZBN (New Zealand Business Number): 13 digits, modelled as COMPANY_NUMBER.
- Companies Office Number: 1-7 digit integer, also COMPANY_NUMBER.
- GST Number (NZ VAT equivalent): the NZBN API does not support GST lookup;
  callers must use search-term fallback. We model GST as IdentifierType.VAT.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

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

_NZBN_RE = re.compile(r"^\d{13}$")
_COMPANY_NUMBER_RE = re.compile(r"^\d{1,7}$")


def _normalize_nzbn(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if not _NZBN_RE.match(cleaned):
        raise InvalidIdentifierError(f"NZBN must be 13 digits: {value}")
    return cleaned


def _normalize_company_number(value: str) -> str:
    cleaned = value.strip().replace(" ", "").lstrip("0")
    if not cleaned:
        raise InvalidIdentifierError(f"NZ company number invalid: {value}")
    if not _COMPANY_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(f"NZ company number must be 1-7 digits: {value}")
    return cleaned


class NZAdapter(CountryAdapter):
    country_code = "NZ"
    country_name = "New Zealand"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = "NZ_NZBN_API_KEY"
    rate_limit_per_minute = 90

    BASE_URL = "https://api.business.govt.nz/services/v5/nzbn"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv(self.api_key_env)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {"Accept": "application/json"}
        return {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Accept": "application/json",
        }

    def _client(self):
        return build_http_client(base_url=self.BASE_URL, headers=self._headers())

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
                    client, "/entities", params={"search-term": "fonterra", "page-size": 1}
                )
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
            notes="Financials available only for large/FMC reporters and overseas companies.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                "/entities",
                params={"search-term": name, "page-size": min(limit, 50)},
            )
            resp.raise_for_status()
            data = resp.json()

        items = _extract_items(data)
        matches: list[CompanyMatch] = []
        for item in items[:limit]:
            nzbn = item.get("nzbn")
            if not nzbn:
                continue
            name_value = (
                item.get("entityName")
                or item.get("tradingName")
                or _first_name(item)
                or ""
            )
            company_number = _extract_company_number(item)
            identifiers = [
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=nzbn,
                    label="NZBN",
                ),
            ]
            if company_number:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=company_number,
                        label="Companies Office Number",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=nzbn,
                    name=name_value,
                    country=self.country_code,
                    identifiers=identifiers,
                    address=_address_from_entity(item),
                    status=item.get("entityStatusDescription") or item.get("entityStatusCode"),
                    source_url=_nzbn_public_url(nzbn),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")

        if id_type == IdentifierType.COMPANY_NUMBER:
            v = value.strip().replace(" ", "")
            if _NZBN_RE.match(v):
                nzbn = _normalize_nzbn(v)
                return await self._lookup_by_nzbn(nzbn)
            cn = _normalize_company_number(v)
            return await self._lookup_by_company_number(cn)

        if id_type == IdentifierType.VAT:
            # GST numbers cannot be looked up directly via the NZBN API; the
            # caller must use search-term. Surface that explicitly.
            raise InvalidIdentifierError(
                "GST (VAT) lookup is not supported by the NZBN API. "
                "Use search_by_name or COMPANY_NUMBER lookup."
            )

        raise InvalidIdentifierError(
            f"NZ supports COMPANY_NUMBER (NZBN or Companies Office #) only, got {id_type}"
        )

    async def _lookup_by_nzbn(self, nzbn: str) -> CompanyDetails | None:
        async with self._client() as client:
            resp = await get_with_retry(client, f"/entities/{nzbn}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        return _details_from_entity(data)

    async def _lookup_by_company_number(self, cn: str) -> CompanyDetails | None:
        async with self._client() as client:
            resp = await get_with_retry(
                client, "/entities", params={"company-number": cn, "page-size": 1}
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        items = _extract_items(data)
        if not items:
            return None
        nzbn = items[0].get("nzbn")
        if not nzbn:
            return _details_from_entity(items[0])
        # The summary item from search omits directors/addresses, so resolve to
        # the full record by NZBN.
        return await self._lookup_by_nzbn(nzbn)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        nzbn = _normalize_nzbn(company_id) if _NZBN_RE.match(company_id.strip()) else None
        if nzbn is None:
            cn = _normalize_company_number(company_id)
            async with self._client() as client:
                resp = await get_with_retry(
                    client, "/entities", params={"company-number": cn, "page-size": 1}
                )
                resp.raise_for_status()
                items = _extract_items(resp.json())
            if not items or not items[0].get("nzbn"):
                return []
            nzbn = items[0]["nzbn"]

        async with self._client() as client:
            resp = await get_with_retry(client, f"/entities/{nzbn}/financial-reports")
            if resp.status_code == 404:
                # Fall back to the documents endpoint.
                resp = await get_with_retry(client, f"/entities/{nzbn}/documents")
                if resp.status_code == 404:
                    return []
            resp.raise_for_status()
            payload = resp.json()

        return _parse_financials(nzbn, payload, years=years)


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "entityList", "entities", "financialReports", "documents"):
        items = payload.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def _first_name(item: dict[str, Any]) -> str | None:
    names = item.get("names") or item.get("entityNames")
    if isinstance(names, list):
        for n in names:
            if isinstance(n, dict) and n.get("name"):
                return n["name"]
    return None


def _extract_company_number(item: dict[str, Any]) -> str | None:
    direct = item.get("companyNumber") or item.get("sourceRegisterUniqueIdentifier")
    if direct:
        return str(direct)
    identifiers = item.get("otherIdentifiers") or item.get("identifiers")
    if isinstance(identifiers, list):
        for ident in identifiers:
            if not isinstance(ident, dict):
                continue
            type_desc = (ident.get("uniqueIdentifierTypeDescription") or "").lower()
            if "company number" in type_desc:
                return str(
                    ident.get("uniqueIdentifier")
                    or ident.get("identifier")
                    or ""
                ) or None
    return None


def _address_from_entity(item: dict[str, Any]) -> str | None:
    addresses = item.get("addresses") or []
    if not isinstance(addresses, list):
        return None
    for a in addresses:
        if not isinstance(a, dict):
            continue
        type_desc = (a.get("addressType") or a.get("addressTypeDescription") or "").upper()
        if type_desc in {"REGISTERED", "PHYSICAL"} or "REGISTERED" in type_desc:
            full = a.get("address1") or a.get("fullAddress") or a.get("address")
            if isinstance(full, str) and full.strip():
                return full.strip()
            parts = [
                a.get("addressLine1"),
                a.get("addressLine2"),
                a.get("addressLine3"),
                a.get("addressLine4"),
                a.get("postCode") or a.get("postalCode"),
                a.get("countryCode"),
            ]
            joined = ", ".join(p for p in parts if p)
            if joined:
                return joined
    return None


def _nzbn_public_url(nzbn: str) -> str:
    return f"https://www.nzbn.govt.nz/mynzbn/nzbndetails/{nzbn}/"


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _details_from_entity(data: dict[str, Any]) -> CompanyDetails:
    nzbn = str(data.get("nzbn") or "")
    name = (
        data.get("entityName")
        or data.get("tradingName")
        or _first_name(data)
        or ""
    )
    inc = _parse_iso_date(data.get("registrationDate"))
    ceased = _parse_iso_date(data.get("deregistrationDate"))

    directors: list[Director] = []
    roles = data.get("roles") or []
    if isinstance(roles, list):
        for r in roles:
            if not isinstance(r, dict):
                continue
            role_type = (r.get("roleType") or r.get("roleTypeDescription") or "").upper()
            if role_type and "DIRECTOR" not in role_type:
                continue
            person = r.get("rolePerson") or r.get("person") or {}
            full_name = (
                person.get("fullName")
                or " ".join(
                    p for p in [person.get("firstName"), person.get("lastName")] if p
                ).strip()
                or r.get("name")
            )
            if not full_name:
                continue
            directors.append(
                Director(
                    name=full_name.strip(),
                    role=r.get("roleTypeDescription") or r.get("roleType"),
                    appointed_on=_parse_iso_date(r.get("appointmentDate")),
                    resigned_on=_parse_iso_date(r.get("ceasedDate")),
                )
            )

    company_number = _extract_company_number(data)
    identifiers = [
        RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=nzbn, label="NZBN"),
    ]
    if company_number:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=company_number,
                label="Companies Office Number",
            )
        )
    # GST is exposed in otherIdentifiers when present.
    other = data.get("otherIdentifiers") or []
    if isinstance(other, list):
        for ident in other:
            if not isinstance(ident, dict):
                continue
            type_desc = (ident.get("uniqueIdentifierTypeDescription") or "").lower()
            value = ident.get("uniqueIdentifier") or ident.get("identifier")
            if value and "gst" in type_desc:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT, value=str(value), label="GST Number"
                    )
                )

    nzsioc = data.get("classificationCodes") or data.get("classifications") or []
    nace_or_sic: list[str] = []
    if isinstance(nzsioc, list):
        for c in nzsioc:
            if isinstance(c, dict):
                code = c.get("classificationCode") or c.get("code")
                if code:
                    nace_or_sic.append(str(code))

    return CompanyDetails(
        id=nzbn,
        name=name,
        country="NZ",
        legal_form=data.get("entityTypeDescription") or data.get("entityType"),
        status=data.get("entityStatusDescription") or data.get("entityStatusCode"),
        incorporation_date=inc,
        dissolution_date=ceased,
        registered_address=_address_from_entity(data),
        capital_amount=None,
        capital_currency="NZD",
        nace_codes=nace_or_sic,
        identifiers=identifiers,
        directors=directors,
        raw=data,
        source_url=_nzbn_public_url(nzbn),
    )


def _parse_financials(
    nzbn: str, payload: Any, *, years: int
) -> list[FinancialFiling]:
    items = _extract_items(payload)
    if not items and isinstance(payload, dict):
        # Sometimes the payload is nested under unknown keys; flatten dict values.
        for v in payload.values():
            if isinstance(v, list):
                items = [x for x in v if isinstance(x, dict)]
                if items:
                    break

    filings: list[FinancialFiling] = []
    from datetime import datetime
    cutoff_year = datetime.utcnow().year - years

    for item in items:
        period_end = (
            _parse_iso_date(item.get("balanceDate"))
            or _parse_iso_date(item.get("financialReportEndDate"))
            or _parse_iso_date(item.get("periodEndDate"))
            or _parse_iso_date(item.get("filingDate"))
            or _parse_iso_date(item.get("documentDate"))
        )
        year_value = item.get("financialYear") or item.get("year")
        try:
            year_int = int(year_value) if year_value is not None else (
                period_end.year if period_end else None
            )
        except (TypeError, ValueError):
            year_int = period_end.year if period_end else None
        if year_int is None:
            continue
        if year_int < cutoff_year:
            continue

        document_url = (
            item.get("documentUrl")
            or item.get("url")
            or item.get("downloadUrl")
            or item.get("href")
        )
        doc_format = item.get("documentFormat") or item.get("format") or item.get("mimeType")
        if isinstance(doc_format, str):
            df = doc_format.lower()
            if "pdf" in df:
                doc_format = "pdf"
            elif "xbrl" in df or "xml" in df:
                doc_format = "xbrl"
            elif "html" in df:
                doc_format = "html"
            elif "json" in df:
                doc_format = "json"

        filings.append(
            FinancialFiling(
                company_id=nzbn,
                year=year_int,
                type=FilingType.ANNUAL_REPORT,
                period_end=period_end,
                currency="NZD",
                structured_data=None,
                document_url=document_url,
                document_format=doc_format,
                source_url=_nzbn_public_url(nzbn),
            )
        )
    return filings
