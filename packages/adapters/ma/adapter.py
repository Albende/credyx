"""Morocco adapter — GLEIF registry backbone + AMF regulated-filing feed.

Source coverage:

* GLEIF (Global Legal Entity Identifier Foundation) — the free, key-less
  golden-copy LEI dataset. Every Moroccan entity with an LEI carries its
  legal name, address, legal form, incorporation date, status and the RC
  (Registre du Commerce) number under ``registeredAs``. GLEIF is an
  explicitly-allowed free aggregator and reachable worldwide, so it powers
  both ``search_by_name`` (full-text, scoped to country MA) and
  ``lookup_by_identifier`` (by LEI).
* OMPIC / DGI — the official commercial register (directinfo.ma) and the
  ICE validator remain paid / CAPTCHA-gated with no free JSON API, so ICE
  and RC lookups raise ``AdapterNotImplementedError`` rather than fabricate.
* AMF regulated-information feed (info-financiere.gouv.fr) — the French
  Autorité des Marchés Financiers publishes, as a free Opendatasoft dataset,
  every regulated filing of issuers with securities admitted on Euronext
  Paris. Moroccan blue-chips cross-listed there (e.g. Maroc Telecom) file
  their audited annual reports / « documents d'enregistrement universel »
  through it, each with a directly-downloadable document URL. Records are
  indexed by LEI, so ``fetch_financials`` resolves them from the same LEI
  GLEIF returns. Issuers that do not file with the AMF surface as an empty
  list — a factual "no public filings" answer, matching the FR convention.

Identifiers:
- LEI             → primary. 20-char alphanumeric, resolvable via GLEIF.
- VAT             → ICE (Identifiant Commun de l'Entreprise), 15 digits.
                    Not resolvable without paid OMPIC access.
- COMPANY_NUMBER  → RC (Registre du Commerce). Not resolvable without paid
                    OMPIC access; GLEIF exposes it as read-only metadata.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

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

logger = logging.getLogger(__name__)

_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")
_ICE_RE = re.compile(r"^\d{15}$")
_YEAR_RE = re.compile(r"20[12]\d")

_GLEIF_BASE = "https://api.gleif.org/api/v1"
_GLEIF_RECORD_UI = "https://search.gleif.org/#/record/"
_GLEIF_HEADERS = {"Accept": "application/vnd.api+json"}

_AMF_BASE = "https://www.info-financiere.gouv.fr/api/v2"
_AMF_DATASET = "flux-amf-new-prod"
_AMF_EXPLORE = (
    "https://www.info-financiere.gouv.fr/explore/dataset/flux-amf-new-prod/table/"
    "?refine.identificationsociete_iso_cd_lei="
)

# AMF "subtype_of_information" values that denote an audited annual filing.
_AMF_ANNUAL_SUBTYPES = {
    "annual financial and audit reports",
    "registration document",
}


def _normalize_lei(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if not _LEI_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Morocco LEI must be 20 alphanumeric characters, got: {value}"
        )
    return cleaned


class MAAdapter(CountryAdapter):
    country_code = "MA"
    country_name = "Morocco"
    identifier_types = [
        IdentifierType.LEI,
        IdentifierType.VAT,
        IdentifierType.COMPANY_NUMBER,
    ]
    primary_identifier = IdentifierType.LEI
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Registry via GLEIF (search + LEI lookup, key-free). Listed-issuer "
            "annual reports via the AMF regulated-filing feed. OMPIC/ICE remain paid."
        )
        try:
            async with build_http_client(timeout=15.0, headers=_GLEIF_HEADERS) as client:
                resp = await get_with_retry(
                    client,
                    f"{_GLEIF_BASE}/lei-records",
                    params={"filter[entity.legalAddress.country]": "MA", "page[size]": 1},
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"GLEIF probe failed: {str(exc)[:160]}",
            )
        status = AdapterStatus.OK if resp.status_code < 400 else AdapterStatus.DEGRADED
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes if status == AdapterStatus.OK else f"GLEIF HTTP {resp.status_code}. {notes}",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = name.strip()
        if not term:
            raise InvalidIdentifierError("Morocco name search requires a non-empty term.")
        async with build_http_client(timeout=20.0, headers=_GLEIF_HEADERS) as client:
            resp = await get_with_retry(
                client,
                f"{_GLEIF_BASE}/lei-records",
                params={
                    "filter[fulltext]": term,
                    "filter[entity.legalAddress.country]": "MA",
                    "page[size]": max(1, min(limit, 50)),
                },
            )
        resp.raise_for_status()
        records = resp.json().get("data", [])
        return [self._match_from_record(rec) for rec in records]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.LEI:
            return await self._lookup_by_lei(_normalize_lei(value))
        if id_type == IdentifierType.VAT:
            raise AdapterNotImplementedError(
                f"Morocco ICE lookup ({value}) requires the paid OMPIC / DGI register. "
                "Resolve the company by LEI (via search_by_name) instead."
            )
        if id_type == IdentifierType.COMPANY_NUMBER:
            raise AdapterNotImplementedError(
                f"Morocco RC lookup ({value}) requires the paid OMPIC commercial register. "
                "Resolve the company by LEI (via search_by_name) instead."
            )
        raise InvalidIdentifierError(
            f"Morocco adapter supports LEI, VAT (ICE) or COMPANY_NUMBER (RC), got {id_type}"
        )

    async def _lookup_by_lei(self, lei: str) -> CompanyDetails | None:
        async with build_http_client(timeout=20.0, headers=_GLEIF_HEADERS) as client:
            resp = await get_with_retry(client, f"{_GLEIF_BASE}/lei-records/{lei}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        record = resp.json().get("data")
        if not record:
            return None
        return self._details_from_record(record)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        stripped = re.sub(r"[\s\-]", "", company_id.strip())
        lei = stripped.upper()
        if not _LEI_RE.match(lei):
            if _ICE_RE.match(stripped):
                return []
            raise InvalidIdentifierError(
                f"Morocco fetch_financials expects an LEI, got: {company_id}"
            )

        async with build_http_client(timeout=30.0) as client:
            resp = await get_with_retry(
                client,
                f"{_AMF_BASE}/catalog/datasets/{_AMF_DATASET}/records",
                params={
                    "where": f'identificationsociete_iso_cd_lei="{lei}"',
                    "order_by": "-informationdeposee_inf_dat_emt",
                    "limit": 100,
                },
            )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        return self._parse_amf_filings(records, lei, years)

    def _parse_amf_filings(
        self, records: list[dict[str, Any]], lei: str, years: int
    ) -> list[FinancialFiling]:
        source_url = f"{_AMF_EXPLORE}{lei}"
        by_year: dict[int, FinancialFiling] = {}
        for entry in records:
            fields = entry.get("record", {}).get("fields", {})
            subtype = (fields.get("subtype_of_information") or "").strip().lower()
            if subtype not in _AMF_ANNUAL_SUBTYPES:
                continue
            title = (fields.get("informationdeposee_inf_tit_inf") or "").strip()
            filed_on = fields.get("informationdeposee_inf_dat_emt")
            year = self._year_from_title(title) or _year_of(filed_on)
            if year is None or year in by_year:
                continue
            url = fields.get("url_de_recuperation") or None
            by_year[year] = FinancialFiling(
                company_id=lei,
                year=year,
                type=FilingType.ANNUAL_REPORT,
                currency="MAD",
                document_url=url,
                document_format=_format_of(url),
                source_url=source_url,
                structured_data={
                    "title": title or None,
                    "amf_subtype": fields.get("subtype_of_information"),
                    "filed_on": filed_on,
                    "isin": fields.get("identificationsociete_iso_cd_isi"),
                },
            )
        ordered = sorted(by_year.values(), key=lambda f: f.year, reverse=True)
        return ordered[:years]

    @staticmethod
    def _year_from_title(title: str) -> int | None:
        candidates = [int(m) for m in _YEAR_RE.findall(title)]
        plausible = [y for y in candidates if y <= datetime.utcnow().year + 1]
        return max(plausible) if plausible else None

    def _match_from_record(self, record: dict[str, Any]) -> CompanyMatch:
        lei = record["id"]
        entity = record["attributes"]["entity"]
        return CompanyMatch(
            id=lei,
            name=entity["legalName"]["name"],
            country="MA",
            identifiers=self._identifiers(lei, entity),
            address=_format_address(entity.get("legalAddress")),
            status=(entity.get("status") or "").lower() or None,
            source_url=f"{_GLEIF_RECORD_UI}{lei}",
        )

    def _details_from_record(self, record: dict[str, Any]) -> CompanyDetails:
        lei = record["id"]
        entity = record["attributes"]["entity"]
        legal_form = entity.get("legalForm") or {}
        return CompanyDetails(
            id=lei,
            name=entity["legalName"]["name"],
            country="MA",
            legal_form=legal_form.get("other"),
            status=(entity.get("status") or "").lower() or None,
            incorporation_date=_parse_date(entity.get("creationDate")),
            registered_address=_format_address(entity.get("legalAddress")),
            capital_amount=None,
            capital_currency="MAD",
            identifiers=self._identifiers(lei, entity),
            raw={"source": "gleif", "lei": lei, "jurisdiction": entity.get("jurisdiction")},
            source_url=f"{_GLEIF_RECORD_UI}{lei}",
        )

    @staticmethod
    def _identifiers(lei: str, entity: dict[str, Any]) -> list[RegistryIdentifier]:
        identifiers = [RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")]
        rc = entity.get("registeredAs")
        if rc:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=str(rc), label="RC")
            )
        return identifiers


def _format_address(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts = list(addr.get("addressLines") or [])
    for key in ("postalCode", "city", "country"):
        value = addr.get(key)
        if value:
            parts.append(str(value))
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _format_of(url: str | None) -> str | None:
    if not url:
        return None
    lowered = url.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".zip"):
        return "zip"
    return None


def _year_of(iso: str | None) -> int | None:
    parsed = _parse_date(iso)
    return parsed.year if parsed else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
