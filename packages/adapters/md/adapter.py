"""Moldova adapter — ASP (Agentia Servicii Publice) state registry.

Moldova has no free public REST API for the state company register. The
two free, public sources used here are:

  * https://www.idno.md/  — community HTML directory keyed by IDNO. Used
    for both name search and per-identifier lookup.
  * https://date.gov.md/  — government open-data portal. Provides
    periodic dataset dumps rather than a live search endpoint, so it is
    referenced as the canonical source URL but not queried at request
    time.

Identifier: IDNO — 13 digits, also serves as the corporate tax number
(fiscal code). The first digit encodes the legal form (1 = SRL/SA/etc.).

No paid services are used. Filings are not centrally available for free
in Moldova; `fetch_financials` returns an empty list per the spec rule
against mock data.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_IDNO_RE = re.compile(r"^\d{13}$")
_IDNO_IN_TEXT_RE = re.compile(r"\b(\d{13})\b")


def _normalize_idno(value: str) -> str:
    # Accept "MD1003600015304", "1003 600 015 304", etc.
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("MD"):
        cleaned = cleaned[2:]
    if not _IDNO_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Moldovan IDNO must be 13 digits, got: {value}"
        )
    return cleaned


class MDAdapter(CountryAdapter):
    country_code = "MD"
    country_name = "Moldova"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    SEARCH_URL = "https://www.idno.md/"
    DETAIL_URL = "https://www.idno.md/company/{idno}/"
    OPEN_DATA_URL = "https://date.gov.md/"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url="https://www.idno.md") as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Moldova has no free REST API. Search/lookup scrape idno.md; "
                "filings are not centrally available — fetch_financials returns []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = quote(name.strip())
        async with build_http_client(base_url="https://www.idno.md") as client:
            resp = await get_with_retry(client, f"/search/?q={query}")
            if resp.status_code >= 500:
                return []
            resp.raise_for_status()
            html = resp.text
        return _parse_search_results(html, limit=limit)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"Moldova supports COMPANY_NUMBER/VAT (IDNO), got {id_type}"
            )
        idno = _normalize_idno(value)
        async with build_http_client(base_url="https://www.idno.md") as client:
            resp = await get_with_retry(client, f"/company/{idno}/")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            html = resp.text
        details = _parse_detail_page(html, idno)
        if details is None:
            return None
        return details

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Moldovan annual financial filings are not published for free in a
        # machine-readable form. BNS aggregates macro data only; ASP filings
        # are paid per document. Per the no-mock-data rule, return [].
        return []


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s)


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_search_results(html: str, *, limit: int) -> list[CompanyMatch]:
    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    # idno.md exposes anchors like <a href="/company/1003600015304/">Name SA</a>
    # within result cards. We extract (idno, name) pairs directly from anchors
    # to be resilient to template changes.
    pattern = re.compile(
        r'<a[^>]+href="/company/(\d{13})/?"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html):
        idno = m.group(1)
        if idno in seen:
            continue
        seen.add(idno)
        name = _collapse_ws(_strip_tags(m.group(2)))
        if not name:
            continue
        matches.append(
            CompanyMatch(
                id=idno,
                name=name,
                country="MD",
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=idno,
                        label="IDNO",
                    ),
                ],
                source_url=f"https://www.idno.md/company/{idno}/",
            )
        )
        if len(matches) >= limit:
            break
    return matches


def _extract_field(html: str, *labels: str) -> str | None:
    # idno.md detail pages render label/value pairs in several layouts. We try
    # a few patterns rather than assume one, since the site updates often.
    for label in labels:
        esc = re.escape(label)
        for pat in (
            rf"<th[^>]*>\s*{esc}\s*</th>\s*<td[^>]*>(.*?)</td>",
            rf"<dt[^>]*>\s*{esc}\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
            rf"<span[^>]*>\s*{esc}\s*</span>\s*<span[^>]*>(.*?)</span>",
            rf"<div[^>]*class=\"[^\"]*label[^\"]*\"[^>]*>\s*{esc}\s*</div>\s*"
            rf"<div[^>]*>(.*?)</div>",
            rf"{esc}\s*:\s*</[^>]+>\s*<[^>]+>(.*?)</",
        ):
            m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                val = _collapse_ws(_strip_tags(m.group(1)))
                if val:
                    return val
    return None


def _parse_detail_page(html: str, idno: str) -> CompanyDetails | None:
    if idno not in html and not _IDNO_IN_TEXT_RE.search(html):
        return None
    name = None
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if title_m:
        name = _collapse_ws(_strip_tags(title_m.group(1)))
    if not name:
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_m:
            name = _collapse_ws(_strip_tags(title_m.group(1)))
    if not name:
        return None

    legal_form = _extract_field(
        html,
        "Forma de organizare", "Forma juridică", "Forma juridica",
        "Legal form",
    )
    status = _extract_field(html, "Statut", "Status", "Stare")
    address = _extract_field(
        html,
        "Adresa juridică", "Adresa juridica", "Adresa",
        "Sediul", "Address",
    )
    activity = _extract_field(
        html,
        "Activitatea principală", "Activitatea principala",
        "Tipul de activitate", "CAEM",
    )
    nace_codes = re.findall(r"\b(\d{2,4})\b", activity or "")

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=idno, label="IDNO"
        ),
        RegistryIdentifier(
            type=IdentifierType.VAT, value=idno, label="Cod fiscal"
        ),
    ]

    return CompanyDetails(
        id=idno,
        name=name,
        country="MD",
        legal_form=legal_form,
        status=status,
        registered_address=address,
        nace_codes=nace_codes[:5],
        identifiers=identifiers,
        raw={"html_length": len(html)},
        source_url=f"https://www.idno.md/company/{idno}/",
    )


