"""Ghana adapter — GSE-listed issuers via free key-less sources.

The official registries are gated and offer no free machine API:

- **RGD / Office of the Registrar of Companies** (rgd.gov.gh, orc.gov.gh,
  eregistrar.rgd.gov.gh) exposes only a login-bound search shell; certified
  extracts are paid per document. No free JSON API.
- **GRA (Ghana Revenue Authority) TIN** validator is a CAPTCHA / session
  form — no free TIN→company resolution.

What *is* free and machine-readable is the listed universe (~40 issuers on
the Ghana Stock Exchange), which also covers the largest Ghanaian corporates
by market cap:

- **GSE-API** (dev.kwayisi.org/apis/gse) — key-less JSON: per-issuer profile
  (legal name, sector, industry, address, contacts, shares, market cap).
- **AFX** (afx.kwayisi.org/gse) — key-less HTML index mapping every GSE
  ticker to its company name, used for name search.
- **AfricanFinancials** (africanfinancials.com) — free per-issuer pages
  listing filed annual reports; each report is a Google-Drive-hosted PDF
  that downloads directly.

Identifier:
- ``OTHER``: the GSE ticker symbol (e.g. ``MTNGH``, ``GCB``, ``EGH``,
  ``TOTAL``). This is the primary identifier because it is the only one that
  resolves against a free source.
- ``COMPANY_NUMBER`` (RGD registration number) and ``VAT`` (GRA TIN) remain
  declared but gated — lookups raise ``AdapterNotImplementedError``.
"""
from __future__ import annotations

import re

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
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_GSE_API_BASE = "https://dev.kwayisi.org/apis/gse"
_AFX_BASE = "https://afx.kwayisi.org/gse"
_AF_BASE = "https://africanfinancials.com"

_TICKER_RE = re.compile(r"^[A-Z0-9]{2,8}$")
_RGD_NUMBER_RE = re.compile(r"^(?:CS|CG|PS|BN|EX|CA)[-/]?\d{6,12}$")
_GRA_TIN_RE = re.compile(r"^[CP]\d{10}$")

_AFX_ROW_RE = re.compile(r'/gse/([a-z0-9]+)\.html title="([^"]+)">([A-Z0-9]+)</a>')
_AF_DRIVE_RE = re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)")

# GSE tickers whose AfricanFinancials ticker differs from the lowercased GSE
# symbol. Everything else resolves as the lowercased ticker.
_AF_TICKER_OVERRIDES = {
    "MTNGH": "mtn",
    "EGH": "ebg",
    "AADS": "aad",
}

_GH_CURRENCY = "GHS"


class GHAdapter(CountryAdapter):
    country_code = "GH"
    country_name = "Ghana"
    identifier_types = [
        IdentifierType.OTHER,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.VAT,
    ]
    primary_identifier = IdentifierType.OTHER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        gse_ok = await self._probe(_GSE_API_BASE, "/equities")
        af_ok = await self._probe(_AF_BASE, "/ghana-listed-company-documents/")
        if not gse_ok:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="GSE-API unreachable",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": af_ok},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "GSE-listed issuers only (search + profile via kwayisi GSE-API, "
                "annual reports via AfricanFinancials). RGD/GRA gated (login + "
                "CAPTCHA + paid extracts)."
                + ("" if af_ok else " [AfricanFinancials unreachable]")
            ),
        )

    async def _probe(self, base_url: str, path: str) -> bool:
        try:
            async with build_http_client(base_url=base_url, timeout=10.0) as client:
                resp = await get_with_retry(client, path, max_attempts=1)
                return resp.status_code < 500
        except Exception:
            return False

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip().lower()
        if not query:
            return []
        async with build_http_client(base_url=_AFX_BASE, timeout=20.0) as client:
            resp = await get_with_retry(client, "/")
            resp.raise_for_status()
            rows = _AFX_ROW_RE.findall(resp.text)

        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for slug, company_name, ticker in rows:
            if ticker in seen:
                continue
            haystack = f"{company_name} {ticker}".lower()
            if query not in haystack:
                continue
            seen.add(ticker)
            matches.append(
                CompanyMatch(
                    id=ticker,
                    name=company_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.OTHER,
                            value=ticker,
                            label="GSE ticker",
                        )
                    ],
                    status="listed",
                    source_url=f"{_AFX_BASE}/{slug}.html",
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        cleaned = value.strip().upper().replace(" ", "")
        if id_type is IdentifierType.COMPANY_NUMBER:
            if not _RGD_NUMBER_RE.match(cleaned):
                raise InvalidIdentifierError(
                    "RGD registration number must look like CS123456789 (CS/CG/PS/"
                    f"BN + 6-12 digits), got: {value}"
                )
            raise AdapterNotImplementedError(
                "Ghana RGD lookup requires a logged-in eRegistrar session; no free "
                "public API. Use the GSE ticker (OTHER) for listed issuers."
            )
        if id_type is IdentifierType.VAT:
            if not _GRA_TIN_RE.match(cleaned):
                raise InvalidIdentifierError(
                    f"GRA TIN must match [C|P]NNNNNNNNNN (11 chars), got: {value}"
                )
            raise AdapterNotImplementedError(
                "Ghana GRA TIN resolution is CAPTCHA-protected; no free public API."
            )
        if id_type is not IdentifierType.OTHER:
            raise InvalidIdentifierError(
                "Ghana supports OTHER (GSE ticker), COMPANY_NUMBER (RGD) or VAT "
                f"(GRA TIN), got {id_type}"
            )
        if not _TICKER_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"GSE ticker must be 2-8 alphanumerics, got: {value}"
            )

        async with build_http_client(base_url=_GSE_API_BASE, timeout=20.0) as client:
            resp = await get_with_retry(client, f"/equities/{cleaned}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
        if not isinstance(payload, dict) or "company" not in payload:
            return None

        company = payload.get("company") or {}
        return CompanyDetails(
            id=cleaned,
            name=company.get("name") or cleaned,
            country=self.country_code,
            status="listed",
            registered_address=company.get("address"),
            capital_currency=_GH_CURRENCY,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.OTHER, value=cleaned, label="GSE ticker"
                )
            ],
            directors=[
                Director(name=d)
                for d in company.get("directors", [])
                if isinstance(d, str) and d.strip()
            ],
            website=_clean_website(company.get("website")),
            phone=company.get("telephone"),
            email=company.get("email"),
            raw=payload,
            source_url=f"{_GSE_API_BASE}/equities/{cleaned}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = company_id.strip().upper().replace(" ", "")
        if not _TICKER_RE.match(ticker):
            return []

        documents = await self._resolve_annual_reports(ticker)
        if not documents:
            return []

        filings: list[FinancialFiling] = []
        for year, doc_slug in documents[: max(years, 1)]:
            document_url = await self._resolve_pdf_url(doc_slug)
            filings.append(
                FinancialFiling(
                    company_id=ticker,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    currency=_GH_CURRENCY,
                    document_url=document_url,
                    document_format="pdf" if document_url else None,
                    source_url=f"{_AF_BASE}/document/{doc_slug}/",
                )
            )
        return filings

    async def _resolve_annual_reports(self, ticker: str) -> list[tuple[int, str]]:
        candidates: list[str] = []
        override = _AF_TICKER_OVERRIDES.get(ticker)
        if override:
            candidates.append(override)
        if ticker.lower() not in candidates:
            candidates.append(ticker.lower())

        for af_ticker in candidates:
            html, status, _ = await fetch_with_bot_bypass(
                f"{_AF_BASE}/company/gh-{af_ticker}/", timeout=45.0
            )
            if status != 200:
                continue
            doc_re = re.compile(
                rf"document/(gh-{re.escape(af_ticker)}-(\d{{4}})-ar-[0-9a-z-]+)/"
            )
            by_year: dict[int, str] = {}
            for doc_slug, year_str in doc_re.findall(html):
                by_year.setdefault(int(year_str), doc_slug)
            if by_year:
                return sorted(by_year.items(), key=lambda kv: kv[0], reverse=True)
        return []

    async def _resolve_pdf_url(self, doc_slug: str) -> str | None:
        html, status, _ = await fetch_with_bot_bypass(
            f"{_AF_BASE}/document/{doc_slug}/", timeout=45.0
        )
        if status != 200:
            return None
        match = _AF_DRIVE_RE.search(html)
        if not match:
            return None
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"


def _clean_website(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        return f"https://{value}"
    return value
