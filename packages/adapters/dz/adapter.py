"""Algeria adapter — COSOB + SGBV (Bourse d'Alger).

Real, free, key-free coverage for the listed-issuer universe of the
Algiers Stock Exchange:

* **COSOB** (Commission d'Organisation et de Surveillance des Opérations
  de Bourse) — https://cosob.dz/emetteurs/informations-financieres/.
  The regulator publishes every listed issuer's filed *états financiers*
  (full annual financial statements) as downloadable PDFs, grouped by
  fiscal year. This is the authoritative filings feed and the live
  issuer directory used for name search.
* **SGBV** (Société de Gestion de la Bourse des Valeurs) —
  https://www.sgbv.dz/. Per-issuer presentation pages
  (``?page=details_societe&id_soc=N``) carry share capital, registered
  contact details, and the legal presentation used to enrich a lookup.

Identifiers:

* ``OTHER``          → the market symbol of the listed issuer
  (e.g. ``SAI`` for Groupe Saidal). Primary identifier — this is what
  ``search_by_name`` returns and what ``lookup_by_identifier`` /
  ``fetch_financials`` consume.
* ``VAT``            → NIF (Numéro d'Identification Fiscale), 15 digits.
* ``COMPANY_NUMBER`` → RC (Registre de Commerce). Both the CNRC Sidjilcom
  registry and the DGI NIF validator sit behind an authenticated session
  (login required, no free JSON contract), so NIF/RC lookups raise
  ``AdapterNotImplementedError`` rather than fabricate a match.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from html import unescape as html_unescape

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import (
    build_http_client,
    fetch_with_bot_bypass,
    get_with_retry,
)
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

_NIF_RE = re.compile(r"^\d{15}$")
_RC_MIN_RE = re.compile(r"^[A-Za-z0-9/\- ]{3,40}$")


@dataclass(frozen=True)
class _Issuer:
    code: str
    name: str
    aliases: tuple[str, ...]
    sgbv_id: int | None = None
    legal_form: str = "Société par actions (SPA)"


# Listed issuers of the Algiers exchange. Aliases are ASCII-folded tokens
# matched against COSOB anchor text (which varies: "SAIDAL", "Groupe
# SAIDAL", "SAIDAL Spa"). ``sgbv_id`` enables SGBV detail enrichment.
_ISSUERS: tuple[_Issuer, ...] = (
    _Issuer("SAI", "Groupe Saidal", ("saidal",), sgbv_id=28),
    _Issuer("ALL", "Alliance Assurances", ("alliance",), sgbv_id=23),
    _Issuer("BIO", "Biopharm", ("biopharm",), sgbv_id=44),
    _Issuer("AUR", "EGH El Aurassi", ("aurassi",), sgbv_id=26),
    _Issuer("CPA", "Crédit Populaire d'Algérie", ("cpa", "credit populaire"), sgbv_id=48),
    _Issuer("BDL", "Banque de Développement Local", ("bdl",), sgbv_id=50),
    _Issuer("AOM", "AOM Invest", ("aom",)),
    _Issuer("ALC", "Alliance Location de véhicules", ("alc",)),
    _Issuer("NCA", "NCA-Rouiba", ("nca", "rouiba")),
    _Issuer("DAH", "Dahli", ("dahli",)),
    _Issuer("MST", "Moustachir", ("moustachir",)),
)

_ISSUER_BY_CODE = {iss.code: iss for iss in _ISSUERS}


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_only.lower()).strip()


def _match_issuer(raw_name: str) -> _Issuer | None:
    folded = _fold(raw_name)
    for iss in _ISSUERS:
        for alias in iss.aliases:
            if re.search(rf"\b{re.escape(alias)}\b", folded):
                return iss
    return None


def _resolve_issuer(value: str) -> _Issuer | None:
    token = value.strip()
    if token.upper() in _ISSUER_BY_CODE:
        return _ISSUER_BY_CODE[token.upper()]
    return _match_issuer(token)


def _normalize_nif(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if cleaned.upper().startswith("DZ"):
        cleaned = cleaned[2:]
    if not _NIF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Algeria NIF must be exactly 15 digits, got: {value}"
        )
    return cleaned


def _normalize_rc(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if not cleaned or not _RC_MIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Algeria RC number empty or malformed: {value}"
        )
    return cleaned


@dataclass
class _CosobEntry:
    year: int
    raw_name: str
    url: str


_YEAR_HEADING_RE = re.compile(r"<h[1-5][^>]*>\s*((?:19|20)\d{2})\s*</h[1-5]>", re.I)
_PDF_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")


class DZAdapter(CountryAdapter):
    country_code = "DZ"
    country_name = "Algeria"
    identifier_types = [
        IdentifierType.OTHER,
        IdentifierType.VAT,
        IdentifierType.COMPANY_NUMBER,
    ]
    primary_identifier = IdentifierType.OTHER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    COSOB_FINANCIALS_URL = "https://cosob.dz/emetteurs/informations-financieres/"
    SGBV_DETAIL_URL = "https://www.sgbv.dz/?page=details_societe&id_soc={id}&lang=fr"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Coverage: Algiers-exchange listed issuers. Filed financial "
            "statements via COSOB; issuer identity/capital via SGBV. CNRC "
            "Sidjilcom and the DGI NIF validator are login-gated (no free "
            "JSON), so NIF/RC lookups are not implemented."
        )
        try:
            _, status, _ = await fetch_with_bot_bypass(
                self.COSOB_FINANCIALS_URL, timeout=20.0
            )
        except httpx.HTTPError as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"COSOB probe failed: {str(exc)[:160]}",
            )
        degraded = status >= 500
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED if degraded else AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=f"COSOB returned HTTP {status}. {notes}" if degraded else notes,
        )

    async def _fetch_cosob_entries(self) -> list[_CosobEntry]:
        html, _, _ = await fetch_with_bot_bypass(
            self.COSOB_FINANCIALS_URL, timeout=30.0
        )
        entries: list[_CosobEntry] = []
        current_year: int | None = None
        for match in re.finditer(
            rf"{_YEAR_HEADING_RE.pattern}|{_PDF_ANCHOR_RE.pattern}", html, re.I | re.S
        ):
            heading_year = match.group(1)
            if heading_year:
                current_year = int(heading_year)
                continue
            if current_year is None:
                continue
            url, inner = match.group(2), match.group(3)
            name = _TAG_RE.sub(" ", inner)
            name = re.sub(r"\s+", " ", name).strip()
            if not name:
                continue
            entries.append(_CosobEntry(current_year, name, url))
        return entries

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = _fold(name)
        if not query:
            raise InvalidIdentifierError("Algeria name search requires a query")
        entries = await self._fetch_cosob_entries()
        seen: dict[str, CompanyMatch] = {}
        for entry in entries:
            issuer = _match_issuer(entry.raw_name)
            if issuer is not None:
                key, display = issuer.code, issuer.name
                source = (
                    self.SGBV_DETAIL_URL.format(id=issuer.sgbv_id)
                    if issuer.sgbv_id
                    else self.COSOB_FINANCIALS_URL
                )
                hay = _fold(display + " " + " ".join(issuer.aliases) + " " + issuer.code)
            else:
                key, display = _fold(entry.raw_name), entry.raw_name
                source = self.COSOB_FINANCIALS_URL
                hay = _fold(entry.raw_name)
            if key in seen:
                continue
            if query in hay or hay in query:
                seen[key] = CompanyMatch(
                    id=key.upper() if issuer else key,
                    name=display,
                    country="DZ",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.OTHER,
                            value=key.upper() if issuer else key,
                            label="Algiers exchange symbol",
                        )
                    ],
                    status="listed",
                    source_url=source,
                )
        return list(seen.values())[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            nif = _normalize_nif(value)
            raise AdapterNotImplementedError(
                f"Algeria NIF lookup ({nif}) requires the DGI validator, "
                "which is login-gated and not a free machine-readable API."
            )
        if id_type == IdentifierType.COMPANY_NUMBER:
            rc = _normalize_rc(value)
            raise AdapterNotImplementedError(
                f"Algeria RC lookup ({rc}) requires the CNRC Sidjilcom portal, "
                "which is login-gated and not a free machine-readable API."
            )
        if id_type != IdentifierType.OTHER:
            raise InvalidIdentifierError(
                "Algeria adapter supports OTHER (market symbol), VAT (NIF) or "
                f"COMPANY_NUMBER (RC), got {id_type}"
            )
        issuer = _resolve_issuer(value)
        if issuer is None:
            return None
        details = CompanyDetails(
            id=issuer.code,
            name=issuer.name,
            country="DZ",
            legal_form=issuer.legal_form,
            status="listed",
            capital_currency="DZD",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=issuer.code,
                    label="Algiers exchange symbol",
                )
            ],
            source_url=(
                self.SGBV_DETAIL_URL.format(id=issuer.sgbv_id)
                if issuer.sgbv_id
                else self.COSOB_FINANCIALS_URL
            ),
        )
        if issuer.sgbv_id is not None:
            await self._enrich_from_sgbv(issuer, details)
        return details

    async def _enrich_from_sgbv(
        self, issuer: _Issuer, details: CompanyDetails
    ) -> None:
        url = self.SGBV_DETAIL_URL.format(id=issuer.sgbv_id)
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(client, url)
        except httpx.HTTPError as exc:
            logger.info("SGBV enrichment failed for %s: %s", issuer.code, exc)
            return
        text = html_unescape(resp.content.decode("utf-8", "ignore"))
        flat = re.sub(r"<[^>]+>", " | ", text)
        flat = re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"\s+", " ", flat))

        capital = re.search(r"Capital Social\s*:?\s*([\d.\s|]+?)\s*DA", flat)
        if capital:
            digits = re.sub(r"\D", "", capital.group(1))
            if digits:
                details.capital_amount = float(digits)

        site = re.search(
            r"Site Officiel\s*:?\s*(?:\|\s*)*((?:https?://|www\.)[^\s|<]+)", flat
        )
        if site:
            details.website = site.group(1).strip().rstrip(".")

        email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", flat)
        if email:
            details.email = email.group(0)

        phone = re.search(
            r"T[eé]l\.?\s*:?\s*(?:\|\s*)*([+0-9][0-9 /]{6,})", flat
        )
        if phone:
            details.phone = phone.group(1).strip(" /")

        denom = re.search(r"D[eé]nomination\s*:?\s*(?:\|\s*)*([^|<]{3,90})", flat)
        if denom:
            details.raw["denomination"] = denom.group(1).strip()

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        if not company_id or not company_id.strip():
            raise InvalidIdentifierError("Algeria company_id is empty")
        issuer = _resolve_issuer(company_id)
        folded = _fold(company_id)
        entries = await self._fetch_cosob_entries()
        matched: list[_CosobEntry] = []
        for entry in entries:
            if "semestre" in _fold(entry.raw_name) or "trimestre" in _fold(entry.raw_name):
                continue
            entry_issuer = _match_issuer(entry.raw_name)
            if issuer is not None:
                if entry_issuer is not None and entry_issuer.code == issuer.code:
                    matched.append(entry)
            elif entry_issuer is None and folded and re.search(
                rf"\b{re.escape(folded)}\b", _fold(entry.raw_name)
            ):
                matched.append(entry)

        if not matched:
            # No listed-issuer filings for this identifier. For a well-formed
            # NIF/RC that simply isn't a listed company this is the factual
            # answer; a non-listed Algerian SPA/SARL files no public accounts.
            cleaned = re.sub(r"[\s\-]", "", company_id.strip())
            if cleaned.upper().startswith("DZ"):
                cleaned = cleaned[2:]
            if _NIF_RE.match(cleaned) or _RC_MIN_RE.match(company_id.strip()):
                return []
            if issuer is None:
                raise InvalidIdentifierError(
                    "Algeria company_id must be an Algiers-exchange symbol "
                    f"(e.g. SAI), a listed-issuer name, a 15-digit NIF or an "
                    f"RC number, got: {company_id}"
                )
            return []

        matched.sort(key=lambda e: e.year, reverse=True)
        result_id = issuer.code if issuer else folded.upper()
        filings: list[FinancialFiling] = []
        for entry in matched[:years]:
            filings.append(
                FinancialFiling(
                    company_id=result_id,
                    year=entry.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(entry.year, 12, 31),
                    currency="DZD",
                    document_url=entry.url,
                    document_format="pdf",
                    source_url=self.COSOB_FINANCIALS_URL,
                )
            )
        return filings
