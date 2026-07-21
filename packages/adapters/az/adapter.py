"""Azerbaijan adapter — State Tax Service (DVX) register + Baku Stock Exchange.

Source coverage:

* Company register (name search + VÖEN lookup) — the public
  ``findTaxpayer`` JSON endpoint that backs the "Kommersiya qurumlarının
  dövlət reyestri məlumatlarının verilməsi" service on the new e-taxes
  single-page app::

      POST https://new.e-taxes.gov.az/api/po/authless/public/v1/authless/findTaxpayer
      {"tin": "9900003871", "type": "legalEntity",
       "serviceCode": "checkLegalName", "isStateRegistry": true}

  Send ``name`` instead of ``tin`` for a name search. No authentication,
  no cookie, no key. Returns the registered name, legal form, charter
  capital, legal address, representative, registration dates and status
  straight from the State Register of Commercial Entities. The legacy
  ``commersialChek.jsp`` HTML page that this adapter used to scrape now
  301-redirects to the SPA and no longer serves data.

* Filed financial statements — the Baku Stock Exchange (Bakı Fond Birjası,
  ``bfb.az``) publishes each listed issuer's audited IFRS annual accounts
  as PDFs on ``/emitent/{slug}``. The AZ-locale issuer slug is a
  transliteration of the registered Azerbaijani name, so a taxpayer's
  register name maps onto the issuer page without needing a paid lookup.
  Non-listed companies do not publish accounts anywhere free, so
  ``fetch_financials`` returns an empty list for them.

Identifier:
- VAT → VÖEN (Vergi Ödəyicisinin Eyniləşdirmə Nömrəsi). Always 10 digits.
  Some sources prefix with "AZ"; we strip it. Same number serves as the
  VAT registration ID and the corporate tax ID.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
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
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_VOEN_RE = re.compile(r"^\d{10}$")

# A well-known active taxpayer used as a liveness probe — SOCAR.
_HEALTH_PROBE_VOEN = "9900003871"

# Azerbaijani Latin letters that carry diacritics, mapped to the ASCII
# forms the Baku Stock Exchange uses when it builds issuer-page slugs.
_AZ_TRANSLIT = str.maketrans(
    {
        "ə": "e", "Ə": "e",
        "ş": "s", "Ş": "s",
        "ç": "c", "Ç": "c",
        "ğ": "g", "Ğ": "g",
        "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o",
        "ü": "u", "Ü": "u",
    }
)

# Legal-form words carried by almost every registered name; they must not
# drive the issuer match, only the distinctive words should.
_SLUG_STOPWORDS = frozenset(
    {
        "aciq", "acig", "qapali", "sehmdar", "cemiyyeti", "cemiyyati",
        "mehdud", "mesuliyyetli", "asc", "qsc", "mmc", "sc",
    }
)


def _normalize_voen(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("AZ"):
        cleaned = cleaned[2:]
    if not _VOEN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Azerbaijan VÖEN must be exactly 10 digits, got: {value}"
        )
    return cleaned


def _parse_az_date(value: str | None) -> date | None:
    """The register renders dates as ISO; tolerate DD.MM.YYYY and slashes."""
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _slugify_az(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.translate(_AZ_TRANSLIT).lower()).strip("-")


def _distinctive_tokens(slug: str) -> set[str]:
    return {t for t in slug.split("-") if t and t not in _SLUG_STOPWORDS}


def _slug_similarity(a: set[str], b: set[str]) -> float:
    """Prefix-tolerant Jaccard — Azerbaijani genitive endings differ."""
    if not a or not b:
        return 0.0
    matched = 0
    for at in a:
        for bt in b:
            if at == bt or (
                min(len(at), len(bt)) >= 5 and (at.startswith(bt) or bt.startswith(at))
            ):
                matched += 1
                break
    union = len(a) + len(b) - matched
    return matched / union if union else 0.0


class AZAdapter(CountryAdapter):
    country_code = "AZ"
    country_name = "Azerbaijan"
    identifier_types = [IdentifierType.VAT]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    ETAXES_BASE = "https://new.e-taxes.gov.az"
    FIND_TAXPAYER_PATH = "/api/po/authless/public/v1/authless/findTaxpayer"
    SERVICE_URL = (
        "https://new.e-taxes.gov.az/etaxes/services/legal-entity-info"
    )

    BSE_BASE = "https://www.bfb.az"
    BSE_INDEX_PATH = "/bazara-baxis"
    BSE_ISSUER_PATH = "/emitent/"

    def _api_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.ETAXES_BASE,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Accept-Language": "az,en;q=0.7,ru;q=0.5",
                "Origin": self.ETAXES_BASE,
                "Referer": self.SERVICE_URL,
            },
            timeout=30.0,
        )

    def _bse_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BSE_BASE,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=30.0,
        )

    async def _find_taxpayer(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        body = {
            "type": "legalEntity",
            "serviceCode": "checkLegalName",
            "isStateRegistry": True,
            **payload,
        }
        resp = await client.post(self.FIND_TAXPAYER_PATH, json=body)
        if resp.status_code in (400, 404):
            return []
        resp.raise_for_status()
        data = resp.json()
        if data.get("applicationErrorCode"):
            return []
        return data.get("taxpayers", [])

    @staticmethod
    def _status_label(taxpayer: dict[str, Any]) -> str | None:
        status = (
            taxpayer.get("legalTaxpayerStatus", {}).get("taxpayerStatus")
            or taxpayer.get("taxpayerStatus")
        )
        if status:
            name = status.get("name", {})
            label = name.get("en") or name.get("az")
            if label:
                return label
        active = taxpayer.get("active")
        if active is True:
            return "active"
        if active is False:
            return "inactive"
        return None

    def _to_match(self, taxpayer: dict[str, Any]) -> CompanyMatch:
        tin = str(taxpayer.get("tin", ""))
        lts = taxpayer.get("legalTaxpayerStatus", {})
        return CompanyMatch(
            id=tin,
            name=taxpayer.get("name", ""),
            country=self.country_code,
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=tin, label="VÖEN"),
            ],
            address=lts.get("legalAddress"),
            status=self._status_label(taxpayer),
            source_url=self.SERVICE_URL,
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with self._api_client() as client:
            taxpayers = await self._find_taxpayer(client, {"name": query})
        return [self._to_match(t) for t in taxpayers[:limit]]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.VAT:
            raise InvalidIdentifierError(
                f"Azerbaijan adapter only supports VAT (VÖEN), got {id_type}"
            )
        voen = _normalize_voen(value)
        async with self._api_client() as client:
            taxpayers = await self._find_taxpayer(client, {"tin": voen})
        if not taxpayers:
            return None

        taxpayer = taxpayers[0]
        lts = taxpayer.get("legalTaxpayerStatus", {})
        legal_form = lts.get("legalForm", {}).get("name", {})
        representative = lts.get("legitimate")
        directors = (
            [Director(name=representative, role="Legal representative")]
            if representative
            else []
        )

        return CompanyDetails(
            id=voen,
            name=taxpayer.get("name") or lts.get("name", ""),
            country=self.country_code,
            legal_form=legal_form.get("en") or legal_form.get("az"),
            status=self._status_label(taxpayer),
            incorporation_date=_parse_az_date(lts.get("stateRegisteredAt")),
            registered_address=lts.get("legalAddress"),
            capital_amount=lts.get("charterCapital"),
            capital_currency="AZN",
            directors=directors,
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=voen, label="VÖEN"),
            ],
            raw={
                "source": "new.e-taxes.gov.az/findTaxpayer",
                "taxpayer": taxpayer,
            },
            source_url=self.SERVICE_URL,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        voen = _normalize_voen(company_id)
        async with self._api_client() as api:
            taxpayers = await self._find_taxpayer(api, {"tin": voen})
        if not taxpayers:
            return []
        name = taxpayers[0].get("name", "")
        if not name:
            return []

        async with self._bse_client() as bse:
            slug = await self._match_issuer_slug(bse, name)
            if not slug:
                return []
            resp = await get_with_retry(bse, f"{self.BSE_ISSUER_PATH}{slug}")
            if resp.status_code != 200:
                return []
            page = resp.text
            issuer_url = f"{self.BSE_BASE}{self.BSE_ISSUER_PATH}{slug}"
            reports = _extract_annual_reports(page)
            filings: list[FinancialFiling] = []
            for year, doc_url in reports[:years]:
                document_url = doc_url if await _document_downloads(bse, doc_url) else None
                filings.append(
                    FinancialFiling(
                        company_id=voen,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        currency="AZN",
                        document_url=document_url,
                        document_format="pdf" if document_url else None,
                        source_url=issuer_url,
                    )
                )
        return filings

    async def _match_issuer_slug(
        self, client: httpx.AsyncClient, name: str
    ) -> str | None:
        resp = await get_with_retry(client, self.BSE_INDEX_PATH)
        if resp.status_code != 200:
            return None
        candidates = {
            m.group(1)
            for m in re.finditer(r"/emitent/([a-z0-9-]+)", resp.text)
        }
        if not candidates:
            return None
        target = _distinctive_tokens(_slugify_az(name))
        if not target:
            return None
        best_slug, best_score = None, 0.0
        for slug in candidates:
            score = _slug_similarity(target, _distinctive_tokens(slug))
            if score > best_score:
                best_slug, best_score = slug, score
        return best_slug if best_score >= 0.6 else None

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._api_client() as client:
                taxpayers = await self._find_taxpayer(
                    client, {"tin": _HEALTH_PROBE_VOEN}
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        if not taxpayers or not taxpayers[0].get("name"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="e-taxes findTaxpayer responded but probe VÖEN returned "
                "no name; the API contract may have changed.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Register search + VÖEN lookup via e-taxes findTaxpayer; "
            "financials via Baku Stock Exchange issuer filings (listed only).",
        )


async def _document_downloads(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.head(url, follow_redirects=True)
    except (httpx.TransportError, httpx.TimeoutException):
        return False
    if resp.status_code != 200:
        return False
    return "pdf" in resp.headers.get("Content-Type", "").lower()


_ANNUAL_HEADING = "İllik maliyyə hesabatları"
_DOC_CARD_RE = re.compile(
    r'doc-card"\s+title="(?P<title>[^"]*)".*?href="(?P<href>[^"]+?\.pdf[^"]*)"',
    re.IGNORECASE | re.DOTALL,
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _extract_annual_reports(html: str) -> list[tuple[int, str]]:
    """Pull ``(year, pdf_url)`` pairs from the issuer's annual-report block.

    The Baku Stock Exchange issuer page renders each filing as a
    ``doc-card`` whose ``title`` carries the year ("2024 İllik Maliyyə
    hesabatı"). We scope to the "İllik maliyyə hesabatları" section so
    semi-annual and other documents are ignored, then keep the newest
    year per document.
    """
    start = html.find(_ANNUAL_HEADING)
    if start == -1:
        return []
    nxt = html.find("<h5", start + len(_ANNUAL_HEADING))
    block = html[start : nxt if nxt != -1 else len(html)]

    by_year: dict[int, str] = {}
    for card in _DOC_CARD_RE.finditer(block):
        year_match = _YEAR_RE.search(card.group("title"))
        if not year_match:
            continue
        year = int(year_match.group(0))
        url = unescape(card.group("href")).strip()
        if not url.startswith("http"):
            url = f"{AZAdapter.BSE_BASE}{url}"
        by_year.setdefault(year, url)
    return sorted(by_year.items(), key=lambda pair: pair[0], reverse=True)
