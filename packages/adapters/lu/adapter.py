"""Luxembourg adapter — GLEIF + VIES + filings.xbrl.org.

Luxembourg's own register (LBR / RCSL) redesigned onto an IBM Tivoli Access
Manager login servlet and no longer exposes a free machine-readable search or
per-company page — the legacy ``mjrcs`` action URLs now 404 or bounce through
``TAMLoginServlet``. The RCSL open-data extract that once lived on
data.public.lu was withdrawn. So this adapter sources the same facts from
three free, key-free, authoritative feeds:

- **GLEIF** (https://api.gleif.org) — the Global LEI index. Every LU record
  carries the RCS number in ``entity.registeredAs`` and the registrar
  ``RA000432`` (= Luxembourg RCS), so GLEIF is a live proxy for name search
  and RCS lookup, and yields the LEI needed for filings.
- **VIES REST** (https://ec.europa.eu/taxation_customs/vies) — confirms an LU
  VAT registration and returns the registered name + address.
- **filings.xbrl.org** — the XBRL International ESEF filings index. LU listed
  companies file their annual financial report as an iXBRL/ESEF package here;
  the API returns real per-filing metadata and a downloadable report package.

Identifier scope:
- COMPANY_NUMBER → RCS B-number ("B82454", "82454", "B 82 454" all valid).
- LEI            → 20-char ISO 17442 code.
- VAT            → LU + 8 digits.

GLEIF only indexes entities that hold an LEI (all listed companies and most
mid/large LU entities do). When a company has no LEI it simply doesn't match —
we never fabricate a registry row. Financials cover ESEF filers (listed
issuers); non-listed accounts remain paid documents on LBR and are not faked.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

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

_LU_VAT_RE = re.compile(r"^\d{8}$")
_LEI_RE = re.compile(r"^[0-9A-Z]{18}[0-9]{2}$")

_HEALTH_PROBE_RCS = "B82454"  # ArcelorMittal — stable LU RCS with an LEI


def _normalize_rcs(value: str) -> str:
    """Return a canonical RCS number like "B82454"."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "")
    if cleaned.startswith("RCS"):
        cleaned = cleaned[3:]
    if cleaned.startswith("B"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit() or not (1 <= len(cleaned) <= 7):
        raise InvalidIdentifierError(
            f"Luxembourg RCS number must be 'B' + digits: {value}"
        )
    return f"B{cleaned}"


def _normalize_lu_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("LU"):
        cleaned = cleaned[2:]
    if not _LU_VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Luxembourg VAT must be 'LU' + 8 digits: {value}"
        )
    return cleaned


def _normalize_lei(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "")
    if not _LEI_RE.match(cleaned):
        raise InvalidIdentifierError(f"LEI must be 20 chars (ISO 17442): {value}")
    return cleaned


class LUAdapter(CountryAdapter):
    country_code = "LU"
    country_name = "Luxembourg"
    identifier_types = [
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.LEI,
        IdentifierType.VAT,
    ]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    VIES_BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api"
    FILINGS_BASE = "https://filings.xbrl.org"
    FILINGS_API = "https://filings.xbrl.org/api/filings"
    GLEIF_RECORD_UI = "https://search.gleif.org/#/record"

    async def health_check(self) -> AdapterHealth:
        caps = {"search": True, "lookup": True, "financials": True}
        try:
            record = await self._gleif_lookup_rcs(_HEALTH_PROBE_RCS)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities=caps,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"GLEIF probe failed: {str(exc)[:160]}",
            )
        if record is None:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities=caps,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="GLEIF reachable but ArcelorMittal RCS not resolved.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities=caps,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + RCS/LEI lookup via GLEIF, VAT via VIES REST, "
                "financials via filings.xbrl.org ESEF index."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        params = {
            "filter[entity.legalName]": name,
            "filter[entity.legalAddress.country]": self.country_code,
            "page[size]": max(1, min(limit, 50)),
        }
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(
                    client, f"{self.GLEIF_BASE}/lei-records", params=params
                )
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        records = (resp.json() or {}).get("data", [])
        matches: list[CompanyMatch] = []
        for record in records[:limit]:
            match = self._record_to_match(record)
            if match is not None:
                matches.append(match)
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.LEI:
            record = await self._gleif_get_by_lei(_normalize_lei(value))
            return self._record_to_details(record) if record else None
        if id_type == IdentifierType.COMPANY_NUMBER:
            record = await self._gleif_lookup_rcs(_normalize_rcs(value))
            return self._record_to_details(record) if record else None
        raise InvalidIdentifierError(
            f"LU supports COMPANY_NUMBER (RCS), LEI or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        lei = await self._resolve_lei(company_id)
        if lei is None:
            return []
        filter_json = (
            '[{"name":"entity.identifier","op":"eq","val":"' + lei + '"}]'
        )
        params = {"filter": filter_json, "page[size]": 100}
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, self.FILINGS_API, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        entries = (resp.json() or {}).get("data", [])
        filings: list[FinancialFiling] = []
        for entry in entries:
            filing = self._entry_to_filing(entry, company_id)
            if filing is not None:
                filings.append(filing)
        filings.sort(key=lambda f: f.period_end or date.min, reverse=True)
        return filings[:years]

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_lu_vat(value)
        url = f"{self.VIES_BASE}/ms/{self.country_code}/vat/{vat}"
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, url)
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        payload = resp.json() or {}
        if not payload.get("isValid"):
            return None
        name = (payload.get("name") or "").strip()
        address = (payload.get("address") or "").strip()
        return CompanyDetails(
            id=f"LU{vat}",
            name=name if name and name != "---" else f"LU{vat}",
            country="LU",
            status="active",
            registered_address=address if address and address != "---" else None,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=f"LU{vat}", label="VAT"),
            ],
            raw={"vies": payload},
            source_url="https://ec.europa.eu/taxation_customs/vies/",
        )

    async def _resolve_lei(self, company_id: str) -> str | None:
        candidate = company_id.strip().upper().replace(" ", "")
        if _LEI_RE.match(candidate):
            return candidate
        record = await self._gleif_lookup_rcs(_normalize_rcs(company_id))
        if record is None:
            return None
        return record.get("attributes", {}).get("lei")

    async def _gleif_lookup_rcs(self, rcs: str) -> dict[str, Any] | None:
        for registered_as in (rcs, rcs[1:]):
            params = {
                "filter[entity.registeredAs]": registered_as,
                "filter[entity.legalAddress.country]": self.country_code,
            }
            async with build_http_client(timeout=30.0) as client:
                try:
                    resp = await get_with_retry(
                        client, f"{self.GLEIF_BASE}/lei-records", params=params
                    )
                except httpx.HTTPError:
                    return None
            if resp.status_code != 200:
                continue
            records = (resp.json() or {}).get("data", [])
            for record in records:
                if (
                    record.get("attributes", {})
                    .get("entity", {})
                    .get("registeredAs", "")
                    .upper()
                    == rcs.upper()
                ):
                    return record
            if records:
                return records[0]
        return None

    async def _gleif_get_by_lei(self, lei: str) -> dict[str, Any] | None:
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(
                    client, f"{self.GLEIF_BASE}/lei-records/{lei}"
                )
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        return (resp.json() or {}).get("data")

    def _record_to_match(self, record: dict[str, Any]) -> CompanyMatch | None:
        attrs = record.get("attributes", {})
        entity = attrs.get("entity", {})
        name = (entity.get("legalName") or {}).get("name")
        if not name:
            return None
        lei = attrs.get("lei") or record.get("id")
        rcs = _clean_rcs(entity.get("registeredAs"))
        identifiers: list[RegistryIdentifier] = []
        local_id = lei
        if rcs:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=rcs, label="RCS")
            )
            local_id = rcs
        if lei:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
            )
        return CompanyMatch(
            id=local_id,
            name=name,
            country=self.country_code,
            identifiers=identifiers,
            address=_format_address(entity.get("legalAddress")),
            status=_map_status(entity.get("status")),
            source_url=f"{self.GLEIF_RECORD_UI}/{lei}" if lei else None,
        )

    def _record_to_details(self, record: dict[str, Any]) -> CompanyDetails | None:
        attrs = record.get("attributes", {})
        entity = attrs.get("entity", {})
        name = (entity.get("legalName") or {}).get("name")
        if not name:
            return None
        lei = attrs.get("lei") or record.get("id")
        rcs = _clean_rcs(entity.get("registeredAs"))
        identifiers: list[RegistryIdentifier] = []
        local_id = lei
        if rcs:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=rcs, label="RCS")
            )
            local_id = rcs
        if lei:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
            )
        return CompanyDetails(
            id=local_id,
            name=name,
            country="LU",
            legal_form=(entity.get("legalForm") or {}).get("id"),
            status=_map_status(entity.get("status")),
            incorporation_date=_parse_date(entity.get("creationDate")),
            registered_address=_format_address(entity.get("legalAddress")),
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"gleif": attrs},
            source_url=f"{self.GLEIF_RECORD_UI}/{lei}" if lei else None,
        )

    def _entry_to_filing(
        self, entry: dict[str, Any], company_id: str
    ) -> FinancialFiling | None:
        attrs = entry.get("attributes", {})
        period_end = _parse_date(attrs.get("period_end"))
        if period_end is None:
            return None
        package_path = attrs.get("package_url")
        report_path = attrs.get("report_url")
        return FinancialFiling(
            company_id=company_id,
            year=period_end.year,
            type=FilingType.ANNUAL_REPORT,
            period_end=period_end,
            currency=None,
            document_url=_absolute_filing_url(package_path),
            document_format="xbrl",
            source_url=_absolute_filing_url(report_path)
            or self.FILINGS_BASE,
        )


def _clean_rcs(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper().replace(" ", "")
    digits = re.sub(r"\D", "", cleaned)
    return f"B{digits}" if digits else None


def _map_status(status: str | None) -> str | None:
    if not status:
        return None
    return "active" if status.upper() == "ACTIVE" else status.lower()


def _format_address(address: dict[str, Any] | None) -> str | None:
    if not address:
        return None
    parts: list[str] = []
    parts.extend(line for line in (address.get("addressLines") or []) if line)
    for key in ("postalCode", "city", "country"):
        value = address.get(key)
        if value:
            parts.append(value)
    joined = ", ".join(p.strip() for p in parts if p and p.strip())
    return joined or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _absolute_filing_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http"):
        return path
    return "https://filings.xbrl.org" + quote(path)
