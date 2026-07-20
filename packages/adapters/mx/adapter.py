"""Mexico adapter — GLEIF (registry identity) + SEC EDGAR (listed-issuer filings).

Mexico has no free official corporate-registry API (SAT's RFC verifier is
CAPTCHA-gated, SIGER/RPC filings are paid per-state). Two free, key-less
sources cover the three adapter capabilities for real data:

- **GLEIF** (https://api.gleif.org) — the global LEI index. Every LEI record
  for a Mexican entity carries its official RFC in ``entity.registeredAs``
  (registration authority ``RA000449`` = SAT), the legal name, legal address,
  status, and ELF legal-form code. This drives name search and RFC lookup.
- **SEC EDGAR** (https://data.sec.gov, https://efts.sec.gov) — Mexican issuers
  cross-listed in the US file their annual report as Form 20-F. Full-text
  search resolves the company name to a CIK; the submissions feed yields the
  real, downloadable filing documents. This drives financials.

Identifier: RFC (Registro Federal de Contribuyentes).
- Personas morales (corporates): 12 chars = 3 letters + 6 digits (YYMMDD
  incorporation date) + 3 alphanumerics ("homoclave").
- Personas físicas: 13 chars — rejected (out of scope for B2B credit).

Coverage note: GLEIF holds Mexican entities that have an LEI (large/regulated
firms and their counterparties); EDGAR financials exist only for the ~30
issuers cross-listed in the US. Companies outside both surfaces resolve to
``None`` / ``[]`` rather than fabricated data (non-negotiable rule #1).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

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

# Persona moral (corporate) RFC: 3 letters, 6 digits (YYMMDD), 3 alphanumerics.
_RFC_MORAL_RE = re.compile(r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$")
# Persona física RFC is 13 chars (4 letters + 6 digits + 3 alphanumerics).
_RFC_FISICA_RE = re.compile(r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$")
_LEI_RE = re.compile(r"^[A-Z0-9]{18}\d{2}$")

# Trailing legal-form tokens stripped from a GLEIF legal name to form a clean
# EDGAR full-text query. GLEIF stores "AMERICA MOVIL S A B DE C V".
_LEGAL_FORM_TOKENS = {
    "S", "A", "B", "C", "V", "DE", "SA", "SAB", "SAPI", "CV", "SC", "RL",
    "EPE", "SOFOM", "ENR", "ER", "MI",
}
# EDGAR display_names embed the padded CIK, e.g. "MEXICAN PETROLEUM  (CIK 0000932782)".
_CIK_RE = re.compile(r"\(CIK (\d{10})\)")
_ANNUAL_FORMS = ("20-F", "40-F")


def _normalize_rfc(value: str) -> str:
    cleaned = (value or "").strip().upper().replace(" ", "").replace("-", "")
    if _RFC_MORAL_RE.match(cleaned):
        return cleaned
    if _RFC_FISICA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"RFC {value} is a persona física (13 chars). MX adapter only "
            "handles personas morales (12 chars)."
        )
    raise InvalidIdentifierError(
        f"RFC invalid: {value}. Expected 12 chars: 3 letters + 6 digits + 3 alphanumerics."
    )


def _incorporation_from_rfc(rfc: str) -> date | None:
    """The 6 digits after the 3-letter prefix encode the SAT-registered
    incorporation date (YYMMDD). Two-digit year pivots on the current year."""
    yy, mm, dd = int(rfc[3:5]), int(rfc[5:7]), int(rfc[7:9])
    century = 2000 if yy <= (datetime.utcnow().year % 100) else 1900
    try:
        return date(century + yy, mm, dd)
    except ValueError:
        return None


def _clean_name_for_edgar(legal_name: str) -> str:
    tokens = legal_name.replace(".", " ").replace(",", " ").split()
    while tokens and tokens[-1].upper() in _LEGAL_FORM_TOKENS:
        tokens.pop()
    return " ".join(tokens).strip()


def _gleif_address(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts = list(addr.get("addressLines") or [])
    for key in ("postalCode", "city", "region", "country"):
        val = addr.get(key)
        if val:
            parts.append(str(val))
    return ", ".join(p for p in parts if p) or None


def _match_from_gleif(record: dict[str, Any]) -> CompanyMatch | None:
    attrs = record.get("attributes") or {}
    entity = attrs.get("entity") or {}
    name = (entity.get("legalName") or {}).get("name")
    if not name:
        return None
    lei = attrs.get("lei")
    rfc = entity.get("registeredAs")
    identifiers: list[RegistryIdentifier] = []
    if rfc:
        identifiers.append(RegistryIdentifier(type=IdentifierType.VAT, value=rfc, label="RFC"))
    if lei:
        identifiers.append(RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI"))
    return CompanyMatch(
        id=rfc or lei or name,
        name=name,
        country="MX",
        identifiers=identifiers,
        address=_gleif_address(entity.get("legalAddress")),
        status=(entity.get("status") or "").lower() or None,
        source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
    )


def _details_from_gleif(rfc: str, record: dict[str, Any]) -> CompanyDetails:
    attrs = record.get("attributes") or {}
    entity = attrs.get("entity") or {}
    lei = attrs.get("lei")
    identifiers = [RegistryIdentifier(type=IdentifierType.VAT, value=rfc, label="RFC")]
    if lei:
        identifiers.append(RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI"))
    legal_form = (entity.get("legalForm") or {}).get("id")
    return CompanyDetails(
        id=rfc,
        name=(entity.get("legalName") or {}).get("name") or rfc,
        country="MX",
        legal_form=legal_form,
        status=(entity.get("status") or "").lower() or None,
        incorporation_date=_incorporation_from_rfc(rfc),
        registered_address=_gleif_address(entity.get("legalAddress")),
        identifiers=identifiers,
        source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
        raw={"gleif": attrs},
    )


class MXAdapter(CountryAdapter):
    country_code = "MX"
    country_name = "Mexico"
    identifier_types = [
        IdentifierType.VAT,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.LEI,
    ]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    GLEIF_BASE_URL = "https://api.gleif.org"
    EDGAR_DATA_URL = "https://data.sec.gov"
    EDGAR_FTS_URL = "https://efts.sec.gov"
    EDGAR_ARCHIVE_URL = "https://www.sec.gov"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.GLEIF_BASE_URL,
                headers={"Accept": "application/vnd.api+json"},
            ) as client:
                resp = await get_with_retry(
                    client,
                    "/api/v1/lei-records",
                    params={"filter[entity.legalAddress.country]": "MX", "page[size]": 1},
                )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes=f"GLEIF unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "Identity via GLEIF (RFC in registeredAs). Financials via SEC "
                "EDGAR 20-F for US-cross-listed Mexican issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = (name or "").strip()
        if not term:
            return []
        size = max(1, min(limit, 50))
        records = await self._gleif_get(
            "/api/v1/lei-records",
            params={
                "filter[entity.legalName]": term,
                "filter[entity.legalAddress.country]": "MX",
                "page[size]": size,
            },
        )
        matches: list[CompanyMatch] = []
        for record in records:
            match = _match_from_gleif(record)
            if match is not None:
                matches.append(match)
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.LEI:
            lei = (value or "").strip().upper()
            if not _LEI_RE.match(lei):
                raise InvalidIdentifierError(f"LEI invalid: {value}")
            record = await self._gleif_record_by_lei(lei)
            if record is None:
                return None
            rfc = (record.get("attributes") or {}).get("entity", {}).get("registeredAs") or lei
            return _details_from_gleif(rfc, record)

        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"MX supports VAT (RFC), COMPANY_NUMBER, or LEI, got {id_type}"
            )
        rfc = _normalize_rfc(value)
        record = await self._gleif_record_by_rfc(rfc)
        if record is None:
            return None
        return _details_from_gleif(rfc, record)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        rfc = _normalize_rfc(company_id)
        record = await self._gleif_record_by_rfc(rfc)
        if record is None:
            return []
        legal_name = (
            (record.get("attributes") or {}).get("entity", {}).get("legalName", {}).get("name")
        )
        if not legal_name:
            return []
        cik = await self._edgar_resolve_cik(_clean_name_for_edgar(legal_name))
        if cik is None:
            return []
        return await self._edgar_annual_filings(rfc, cik, years)

    # --- GLEIF ---------------------------------------------------------------

    async def _gleif_get(
        self, path: str, *, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        async with build_http_client(
            base_url=self.GLEIF_BASE_URL,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, path, params=params)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json().get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    async def _gleif_record_by_rfc(self, rfc: str) -> dict[str, Any] | None:
        records = await self._gleif_get(
            "/api/v1/lei-records",
            params={
                "filter[entity.registeredAs]": rfc,
                "filter[entity.legalAddress.country]": "MX",
                "page[size]": 1,
            },
        )
        return records[0] if records else None

    async def _gleif_record_by_lei(self, lei: str) -> dict[str, Any] | None:
        records = await self._gleif_get(f"/api/v1/lei-records/{lei}", params={})
        return records[0] if records else None

    # --- SEC EDGAR -----------------------------------------------------------

    async def _edgar_resolve_cik(self, query: str) -> str | None:
        if not query:
            return None
        async with build_http_client(
            base_url=self.EDGAR_FTS_URL, headers={"Accept": "application/json"}
        ) as client:
            resp = await get_with_retry(
                client,
                "/LATEST/search-index",
                params={"q": f'"{query}"', "forms": ",".join(_ANNUAL_FORMS)},
            )
        if resp.status_code != 200:
            return None
        hits = (resp.json().get("hits") or {}).get("hits") or []
        counts: dict[str, int] = {}
        for hit in hits:
            for name in (hit.get("_source") or {}).get("display_names") or []:
                m = _CIK_RE.search(name)
                if m:
                    counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

    async def _edgar_annual_filings(
        self, rfc: str, cik: str, years: int
    ) -> list[FinancialFiling]:
        async with build_http_client(
            base_url=self.EDGAR_DATA_URL, headers={"Accept": "application/json"}
        ) as client:
            resp = await get_with_retry(client, f"/submissions/CIK{cik}.json")
        if resp.status_code != 200:
            return []
        recent = (resp.json().get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        acc_nums = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        filing_dates = recent.get("filingDate") or []
        report_dates = recent.get("reportDate") or []

        cik_int = int(cik)
        by_year: dict[int, FinancialFiling] = {}
        for i, form in enumerate(forms):
            if not any(form.startswith(f) for f in _ANNUAL_FORMS):
                continue
            report = report_dates[i] if i < len(report_dates) else ""
            filed = filing_dates[i] if i < len(filing_dates) else ""
            year_src = report or filed
            if not year_src:
                continue
            year = int(year_src[:4])
            if year in by_year:
                continue
            acc = acc_nums[i]
            acc_nodash = acc.replace("-", "")
            doc = docs[i] if i < len(docs) else ""
            document_url = (
                f"{self.EDGAR_ARCHIVE_URL}/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
                if doc
                else None
            )
            by_year[year] = FinancialFiling(
                company_id=rfc,
                year=year,
                type=FilingType.ANNUAL_REPORT,
                period_end=_parse_date(report),
                document_url=document_url,
                document_format="html" if doc.endswith((".htm", ".html")) else "txt",
                source_url=(
                    f"{self.EDGAR_ARCHIVE_URL}/Archives/edgar/data/{cik_int}/"
                    f"{acc_nodash}/{acc}-index.htm"
                ),
            )
        ordered = sorted(by_year.values(), key=lambda f: f.year, reverse=True)
        return ordered[: max(1, years)]


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
