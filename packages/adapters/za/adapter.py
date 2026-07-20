"""South Africa adapter — GLEIF registry mirror + SEC EDGAR (dual-listed).

Free public, key-free sources only.

- **Registry / search / lookup** — the CIPC's own machine surfaces are gated:
  eServices (https://eservices.cipc.co.za/) sells extracts behind an
  authenticated account, and BizPortal's BizProfile now redirects to a
  login (POPIA, since 2024), so neither is scrapeable key-free. The free
  key-less route to CIPC-sourced data is **GLEIF** — every South African
  entity with an LEI carries its CIPC registration number in
  `entity.registeredAs` (registration authority CIPC), plus legal name,
  legal form, status and registered address. GLEIF is an approved free
  aggregator per the project rules.

- **Financials** — CIPC annual financial statements are paid eServices
  documents. For the largest South African issuers that are *dual-listed
  in the US* (Sasol, Gold Fields, AngloGold Ashanti, Sibanye-Stillwater,
  Harmony, DRDGold, …) the audited annual report is filed with the US SEC
  as **Form 20-F** and served free, key-free, and per-company from EDGAR.
  We resolve the entity to its EDGAR CIK by name, confirm it is a South
  African filer, and return the real filed 20-F documents. Purely
  JSE-only issuers have no free programmatic financial-statement surface,
  so `fetch_financials` returns `[]` for them rather than fabricate.

Identifiers
- `COMPANY_NUMBER` — CIPC registration number `YYYY/NNNNNN/NN` (year,
  sequence, entity-type suffix e.g. `/06` = (Pty)/Ltd, `/07` = public,
  `/08` = NPC). Stored by CIPC without forced sequence padding, so we
  preserve the digits given.
- `VAT` — 10-digit SARS VAT number starting with `4`. SARS exposes no free
  validation API; we normalize but do not resolve it.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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

logger = logging.getLogger(__name__)

_REG_RE = re.compile(r"^(\d{4})[\s/\-]?(\d{4,8})[\s/\-]?(\d{2})$")
_VAT_RE = re.compile(r"^4\d{9}$")
_CIK_RE = re.compile(r"<CIK>(\d+)</CIK>", re.IGNORECASE)

_CORP_SUFFIXES = {
    "LIMITED", "LTD", "PLC", "GROUP", "HOLDINGS", "HOLDING", "INC",
    "CORP", "CORPORATION", "COMPANY", "CO", "SA", "NV", "AG",
    "PROPRIETARY", "PTY", "SOC", "RF", "THE",
}
_EDGAR_ANNUAL_FORMS = {"20-F", "40-F"}
# EDGAR's internal state/country code for South Africa.
_EDGAR_ZA_CODES = {"T3", "ZA"}


def _normalize_company_number(value: str) -> str:
    """Parse the CIPC YYYY/NNNNNN/NN format, tolerating spaces / dashes.

    CIPC stores the sequence without a fixed width, so we preserve the
    digit count given rather than pad it — padding breaks exact matching
    against the registry-sourced value.
    """
    cleaned = value.strip().upper().replace(" ", "")
    match = _REG_RE.match(cleaned)
    if not match:
        raise InvalidIdentifierError(
            f"ZA registration number must be YYYY/NNNNNN/NN: {value}"
        )
    year, seq, suffix = match.groups()
    return f"{year}/{seq}/{suffix}"


def _reg_variants(reg: str) -> list[str]:
    """Sequence-padding variants CIPC / GLEIF may have stored the number as."""
    year, seq, suffix = reg.split("/")
    core = seq.lstrip("0") or "0"
    variants = {reg}
    for width in (6, 7):
        variants.add(f"{year}/{core.zfill(width)}/{suffix}")
    return list(variants)


def _normalize_vat(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip())
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"ZA VAT number must be 10 digits starting with 4: {value}"
        )
    return cleaned


def _core_name(name: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", name.upper())
    kept = [t for t in tokens if t not in _CORP_SUFFIXES]
    return " ".join(kept or tokens)


def _name_matches(target_core: str, edgar_name: str) -> bool:
    other = _core_name(edgar_name)
    if not target_core or not other:
        return False
    return target_core == other or other.startswith(target_core) or target_core.startswith(other)


def _address_from_gleif(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts = [
        *(addr.get("addressLines") or []),
        addr.get("city"),
        addr.get("region"),
        addr.get("postalCode"),
        addr.get("country"),
    ]
    joined = ", ".join(p for p in parts if p)
    return joined or None


class ZAAdapter(CountryAdapter):
    country_code = "ZA"
    country_name = "South Africa"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 60

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    EDGAR_BASE = "https://www.sec.gov"
    DATA_BASE = "https://data.sec.gov"

    def __init__(self) -> None:
        # SEC requires a descriptive UA with a contact; reuse the same env
        # knob the US adapter reads.
        contact = os.getenv("SEC_EDGAR_USER_AGENT", "CreditLens dev contact@example.com")
        self._edgar_headers = {"User-Agent": contact, "Accept-Encoding": "gzip, deflate"}

    def _gleif_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._gleif_client() as client:
                resp = await get_with_retry(
                    client,
                    "/lei-records",
                    params={
                        "filter[entity.legalAddress.country]": "ZA",
                        "page[size]": 1,
                    },
                )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "GLEIF for search + CIPC-number lookup; SEC EDGAR 20-F for "
                "US-dual-listed issuers' annual reports. JSE-only issuers "
                "have no free financials surface."
            ),
        )

    async def _gleif_records(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        scoped = {"filter[entity.legalAddress.country]": "ZA", **params}
        async with self._gleif_client() as client:
            try:
                resp = await get_with_retry(client, "/lei-records", params=scoped)
            except httpx.HTTPError as exc:
                raise AdapterError(f"GLEIF request failed: {exc}") from exc
        if resp.status_code == 404:
            return []
        if resp.status_code >= 500:
            raise AdapterError(f"GLEIF returned HTTP {resp.status_code}.")
        resp.raise_for_status()
        return resp.json().get("data", [])

    def _match_from_record(self, record: dict[str, Any]) -> CompanyMatch:
        attrs = record["attributes"]
        entity = attrs["entity"]
        lei = attrs["lei"]
        reg = entity.get("registeredAs")
        identifiers = [
            RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
        ]
        if reg:
            identifiers.insert(
                0,
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=reg,
                    label="CIPC Registration Number",
                ),
            )
        return CompanyMatch(
            id=reg or lei,
            name=entity["legalName"]["name"],
            country="ZA",
            identifiers=identifiers,
            address=_address_from_gleif(entity.get("legalAddress")),
            status=(entity.get("status") or None),
            source_url=f"https://search.gleif.org/#/record/{lei}",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not name or not name.strip():
            return []
        records = await self._gleif_records(
            {"filter[entity.legalName]": name.strip(), "page[size]": min(limit, 50)}
        )
        return [self._match_from_record(r) for r in records[:limit]]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            vat = _normalize_vat(value)
            raise AdapterNotImplementedError(
                f"ZA VAT lookup not available without paid SARS access (got {vat})."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"ZA supports COMPANY_NUMBER or VAT, got {id_type}"
            )

        reg = _normalize_company_number(value)
        record: dict[str, Any] | None = None
        for variant in _reg_variants(reg):
            records = await self._gleif_records(
                {"filter[entity.registeredAs]": variant, "page[size]": 5}
            )
            if records:
                record = records[0]
                break
        if record is None:
            return None

        attrs = record["attributes"]
        entity = attrs["entity"]
        registration = attrs.get("registration") or {}
        lei = attrs["lei"]
        stored_reg = entity.get("registeredAs") or reg
        legal_form = (entity.get("legalForm") or {}).get("other")
        inc_date = _parse_iso_date(registration.get("initialRegistrationDate"))

        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=stored_reg,
                label="CIPC Registration Number",
            ),
            RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI"),
        ]
        return CompanyDetails(
            id=stored_reg,
            name=entity["legalName"]["name"],
            country="ZA",
            legal_form=legal_form,
            status=(entity.get("status") or None),
            incorporation_date=inc_date,
            registered_address=_address_from_gleif(entity.get("legalAddress")),
            capital_currency="ZAR",
            identifiers=identifiers,
            raw={"gleif": attrs},
            source_url=f"https://search.gleif.org/#/record/{lei}",
            fetched_at=datetime.utcnow(),
        )

    async def _resolve_name(self, company_id: str) -> str | None:
        """Company id may be a CIPC number (resolve to legal name) or a name."""
        try:
            reg = _normalize_company_number(company_id)
        except InvalidIdentifierError:
            return company_id.strip() or None
        for variant in _reg_variants(reg):
            records = await self._gleif_records(
                {"filter[entity.registeredAs]": variant, "page[size]": 1}
            )
            if records:
                return records[0]["attributes"]["entity"]["legalName"]["name"]
        return None

    async def _find_edgar_cik(self, target_name: str) -> str | None:
        target_core = _core_name(target_name)
        if not target_core:
            return None
        params = {
            "action": "getcompany",
            "company": target_core,
            "type": "20-F",
            "count": "10",
            "output": "atom",
        }
        async with build_http_client(headers=self._edgar_headers) as client:
            resp = await get_with_retry(
                client, f"{self.EDGAR_BASE}/cgi-bin/browse-edgar", params=params
            )
            if resp.status_code >= 400:
                return None
            ciks = list(dict.fromkeys(_CIK_RE.findall(resp.text)))
        for cik in ciks[:5]:
            submissions = await self._edgar_submissions(cik)
            if submissions is None:
                continue
            if not _name_matches(target_core, submissions.get("name", "")):
                continue
            country = (
                (submissions.get("addresses") or {}).get("business") or {}
            ).get("stateOrCountry") or (
                (submissions.get("addresses") or {}).get("mailing") or {}
            ).get("stateOrCountry")
            if country and country not in _EDGAR_ZA_CODES:
                continue
            return cik.lstrip("0").zfill(10)
        return None

    async def _edgar_submissions(self, cik: str) -> dict[str, Any] | None:
        padded = cik.lstrip("0").zfill(10)
        async with build_http_client(headers=self._edgar_headers) as client:
            resp = await get_with_retry(
                client, f"{self.DATA_BASE}/submissions/CIK{padded}.json"
            )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise AdapterError(f"EDGAR submissions {resp.status_code} for CIK {padded}.")
        return resp.json()

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        name = await self._resolve_name(company_id)
        if not name:
            return []
        cik = await self._find_edgar_cik(name)
        if cik is None:
            return []
        submissions = await self._edgar_submissions(cik)
        if submissions is None:
            return []

        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        report_dates = recent.get("reportDate") or []
        filing_dates = recent.get("filingDate") or []

        cutoff = datetime.utcnow().year - years
        cik_int = int(cik)
        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for form, acc, doc, rd, fd in zip(
            forms, accessions, primary_docs, report_dates, filing_dates
        ):
            if form not in _EDGAR_ANNUAL_FORMS:
                continue
            period = rd or fd
            try:
                year = int(period[:4])
            except (ValueError, TypeError):
                continue
            if year < cutoff or year in seen_years:
                continue
            seen_years.add(year)
            acc_nodash = acc.replace("-", "")
            document_url = (
                f"{self.EDGAR_BASE}/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
                if doc
                else None
            )
            filings.append(
                FinancialFiling(
                    company_id=company_id,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=_parse_iso_date(rd),
                    currency=None,
                    document_url=document_url,
                    document_format=_doc_format(doc),
                    source_url=(
                        f"{self.EDGAR_BASE}/Archives/edgar/data/{cik_int}/"
                        f"{acc_nodash}/{acc}-index.htm"
                    ),
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


def _doc_format(doc: str | None) -> str | None:
    if not doc:
        return None
    lowered = doc.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith((".htm", ".html")):
        return "html"
    if lowered.endswith(".xml"):
        return "xbrl"
    return None
