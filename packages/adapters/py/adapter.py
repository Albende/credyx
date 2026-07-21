"""Paraguay adapter — Bolsa de Valores de Asunción (BVA) listed issuers.

Paraguay has no free, machine-readable national company registry: the
DNIT/SET RUC services (``servicios.set.gov.py``) are geoblocked to
Paraguayan IPs and gated behind an AES-obfuscated public-consultation
endpoint, and the register itself is only published as bulk ZIP dumps.
The one free, key-less, live source with both company data *and* filed
financial statements is the BVA issuer directory
(https://www.bolsadevalores.com.py/), which publishes, per listed issuer,
a public detail page plus the audited balance sheets ("Estados
Financieros") the issuer files with the exchange.

Coverage is therefore limited to BVA-listed issuers (corporates, banks and
investment funds that have registered securities). The stable identifier
is the issuer's BVA directory code — the slug of its
``/emisores/{slug}/`` page — surfaced as ``COMPANY_NUMBER``.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import date, datetime

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

_BVA_BASE = "https://www.bolsadevalores.com.py"
_LISTADO_URL = f"{_BVA_BASE}/listado-de-emisores/"

_SLUG_RE = re.compile(r"/emisores/([a-z0-9][a-z0-9-]+)/")
_NON_ISSUER_SLUGS = {"feed"}

_ZIP_ANCHOR_RE = re.compile(
    r'<a[^>]+href="([^"]+\.zip)"[^>]*>\s*([^<]+?)\s*</a>', re.IGNORECASE
)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_FIELD_RE = re.compile(
    r'jet-listing-dynamic-field__content"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_MAILTO_RE = re.compile(r'mailto:([^"?]+)', re.IGNORECASE)
_DYNAMIC_LINK_RE = re.compile(
    r'jet-listing-dynamic-link"><a[^>]+href="\s*(https?://[^"]+?)\s*"', re.IGNORECASE
)
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_PHONE_RE = re.compile(r"\(?\+?595[\d\s()\-]{5,}")
_ADDRESS_HINT = re.compile(
    r"\b(avda|av\.|avenida|calle|ruta|km|barrio|edificio|piso|c/|esq)", re.IGNORECASE
)

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_MONTH_END = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}
_MONTH_RE = re.compile("|".join(_MONTHS), re.IGNORECASE)

_SOCIAL_HOSTS = (
    "facebook.", "twitter.", "x.com", "instagram.", "linkedin.", "youtube.",
    "youtu.be", "wa.me", "whatsapp", "t.me", "tiktok.", "bolsadevalores.com.py",
    "google.", "wp.com", "gravatar.",
)


def _strip_accents(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )


def _slugify(value: str) -> str:
    ascii_value = _strip_accents(value).lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")


def _deslugify(slug: str) -> str:
    core = re.sub(r"-\d+$", "", slug)
    return re.sub(r"\s+", " ", core.replace("-", " ")).strip().upper()


def _clean_slug(value: str) -> str:
    slug = value.strip().strip("/").lower()
    if slug.startswith("http"):
        match = _SLUG_RE.search(slug)
        slug = match.group(1) if match else slug
    slug = slug.rsplit("/emisores/", 1)[-1].strip("/")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", slug):
        raise InvalidIdentifierError(
            f"Paraguay issuer id must be a BVA emisor slug, got: {value}"
        )
    return slug


class PYAdapter(CountryAdapter):
    country_code = "PY"
    country_name = "Paraguay"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    _HEALTH_SLUG = "codipsa-2"

    def __init__(self) -> None:
        self._index: dict[str, str] | None = None
        self._index_lock = asyncio.Lock()

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(
                    client, f"{_BVA_BASE}/emisores/{self._HEALTH_SLUG}/", max_attempts=2
                )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"BVA unreachable: {exc}"[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "BVA (Bolsa de Valores de Asunción) listed issuers only. "
                "Company data + filed balance sheets (Estados Financieros). "
                "No free national registry exists for private companies."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = _strip_accents((name or "").strip()).lower()
        if not term:
            return []
        index = await self._load_index()

        scored: list[tuple[int, str, str]] = []
        for slug, display in index.items():
            haystack = _strip_accents(f"{slug} {display}").lower()
            if term in haystack:
                rank = 0 if haystack.startswith(term) else 1
                scored.append((rank, slug, display))
        scored.sort(key=lambda x: (x[0], x[1]))

        matches: list[CompanyMatch] = []
        for _, slug, display in scored[: max(1, limit)]:
            matches.append(
                CompanyMatch(
                    id=slug,
                    name=display,
                    country="PY",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=slug,
                            label="BVA emisor",
                        )
                    ],
                    source_url=f"{_BVA_BASE}/emisores/{slug}/",
                )
            )

        real_names = await asyncio.gather(
            *(self._issuer_name(m.id) for m in matches), return_exceptions=True
        )
        for match, real in zip(matches, real_names):
            if isinstance(real, str) and real:
                match.name = real
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Paraguay only supports COMPANY_NUMBER (BVA emisor id), got {id_type}"
            )
        slug = _clean_slug(value)
        html = await self._fetch_issuer_page(slug)
        if html is None:
            return None
        return _details_from_page(slug, html)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        slug = _clean_slug(company_id)
        html = await self._fetch_issuer_page(slug)
        if html is None:
            return []

        filings = _filings_from_page(slug, html)
        if not filings:
            return []
        filings.sort(key=lambda f: (f.year, f.period_end or date(f.year, 1, 1)), reverse=True)
        kept_years = sorted({f.year for f in filings}, reverse=True)[: max(1, years)]
        return [f for f in filings if f.year in kept_years]

    async def _load_index(self) -> dict[str, str]:
        if self._index is not None:
            return self._index
        async with self._index_lock:
            if self._index is not None:
                return self._index
            index: dict[str, str] = {}
            try:
                async with build_http_client(timeout=25.0) as client:
                    resp = await get_with_retry(client, _LISTADO_URL)
                    resp.raise_for_status()
                    body = resp.text
            except httpx.HTTPError:
                self._index = {}
                return self._index
            for slug in _SLUG_RE.findall(body):
                if slug in _NON_ISSUER_SLUGS or slug in index:
                    continue
                index[slug] = _deslugify(slug)
            self._index = index
            return self._index

    async def _fetch_issuer_page(self, slug: str) -> str | None:
        try:
            async with build_http_client(timeout=25.0) as client:
                resp = await get_with_retry(client, f"{_BVA_BASE}/emisores/{slug}/")
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError:
            return None

    async def _issuer_name(self, slug: str) -> str | None:
        html = await self._fetch_issuer_page(slug)
        if html is None:
            return None
        return _issuer_title(html)


def _issuer_title(html: str) -> str | None:
    match = _TITLE_RE.search(html)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    title = re.split(r"\s[-–|]\s", title, maxsplit=1)[0].strip()
    return title or None


def _dynamic_fields(html: str) -> list[str]:
    fields: list[str] = []
    for raw in _FIELD_RE.findall(html):
        text = re.sub(r"\s+", " ", _TAG_RE.sub("", raw)).strip()
        if text and text not in {"-", "–"}:
            fields.append(text)
    return fields


def _details_from_page(slug: str, html: str) -> CompanyDetails:
    name = _issuer_title(html) or _deslugify(slug)

    email_match = _MAILTO_RE.search(html)
    email = email_match.group(1).strip().lower() if email_match else None

    website = None
    for href in _DYNAMIC_LINK_RE.findall(html):
        low = href.lower()
        if "mailto" in low or any(host in low for host in _SOCIAL_HOSTS):
            continue
        website = href.strip()
        break

    address: str | None = None
    phone: str | None = None
    sector: str | None = None
    for field in _dynamic_fields(html):
        if phone is None and _PHONE_RE.search(field):
            phone = field
            continue
        if address is None and _ADDRESS_HINT.search(field):
            address = field
            continue
        if sector is None and len(field) > 15 and " " in field and not field.isdigit():
            sector = field

    raw: dict[str, str] = {"bva_slug": slug}
    if sector:
        raw["sector"] = sector

    return CompanyDetails(
        id=slug,
        name=name,
        country="PY",
        legal_form=None,
        status="listed",
        registered_address=address,
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=slug, label="BVA emisor"
            )
        ],
        website=website,
        phone=phone,
        email=email,
        raw=raw,
        source_url=f"{_BVA_BASE}/emisores/{slug}/",
    )


def _filings_from_page(slug: str, html: str) -> list[FinancialFiling]:
    filings: list[FinancialFiling] = []
    seen: set[str] = set()
    page_url = f"{_BVA_BASE}/emisores/{slug}/"
    for url, raw_text in _ZIP_ANCHOR_RE.findall(html):
        year_match = _YEAR_RE.search(raw_text)
        if not year_match:
            continue
        if url in seen:
            continue
        seen.add(url)
        year = int(year_match.group(0))
        period_end = _period_end(raw_text, year)
        filings.append(
            FinancialFiling(
                company_id=slug,
                year=year,
                type=FilingType.BALANCE_SHEET,
                period_end=period_end,
                currency="PYG",
                document_url=url if url.startswith("http") else f"{_BVA_BASE}{url}",
                document_format="zip",
                source_url=page_url,
            )
        )
    return filings


def _period_end(text: str, year: int) -> date:
    month_match = _MONTH_RE.search(text)
    month = _MONTHS[month_match.group(0).lower()] if month_match else 12
    day = _MONTH_END[month]
    if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        day = 29
    return date(year, month, day)
