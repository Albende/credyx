"""Armenia adapter — State Register of Legal Entities (e-register.moj.am).

Source coverage:

* https://e-register.moj.am/ — the State Register of Legal Entities of the
  Republic of Armenia, operated by the Ministry of Justice. It replaced the
  old ``e-register.am`` portal (which now redirects here). The public search
  is server-rendered: ``/en/search/companies?query=...`` returns an HTML list
  of matching companies, each linking to a per-company card at
  ``/en/companies/{unique_id}``. The card exposes the state registration
  number, registration date, tax id (TIN / ՀՎՀՀ), the internal unique
  identifier, and the registered address. No authentication. The search index
  matches on company name, TIN, and registration number, so all three can be
  resolved through the same endpoint.
* https://amx.am/ (Armenia Securities Exchange) and https://cda.am/ (Central
  Depository) host listed-issuer financial statements but are served behind a
  Cloudflare edge that IP-bans this environment. https://azdarar.am/ (the
  official public-notifications bulletin where joint-stock companies publish
  audited statements) and https://cba.am/ (Central Bank, bank statements) are
  geo-restricted to Armenia. None are usable as a free financial-statements
  feed from outside Armenia, so ``fetch_financials`` raises
  ``AdapterNotImplementedError`` rather than fabricating data.

Note on coverage: banks and other financial institutions (Ardshinbank,
Ameriabank, etc.) are licensed and supervised through the Central Bank and do
not appear in this Ministry-of-Justice register search. Non-financial
companies — LLCs, CJSCs, OJSCs — are covered.

Identifier:
- VAT → TIN / ՀՎՀՀ (Hark Vcharoghi Hashvarkayin Hamar). 8 digits. Some
  sources prefix with ``AM``; we strip it. The same number serves as the VAT
  registration ID and the corporate tax ID.
- COMPANY_NUMBER → state-registry serial. Rendered in ``NNN.NNN.NNNNNNN``
  form (e.g. ``286.120.1110041``). We pass it through with whitespace
  stripped.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from html import unescape
from typing import Any

import httpx

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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_TIN_RE = re.compile(r"^\d{8}$")
_REG_NUM_RE = re.compile(r"^[0-9./\-]{3,32}$")

# "UCOM" CJSC — a well-known, in-register liveness probe (TIN 00024873).
_HEALTH_PROBE_NAME = "UCOM"

_LEGAL_FORM_SUFFIXES = (
    "CJSC",
    "OJSC",
    "LLC",
    "JSC",
    "PBE",
    "SNCO",
    "LTD",
)

_LABEL_REG_NUMBER = (
    "registration number",
    "state registration number",
    "պետական գրանցման համար",
    "գրանցման համար",
    "регистрационный номер",
)
_LABEL_REG_DATE = (
    "registration date",
    "date of registration",
    "գրանցման ամսաթիվ",
    "дата регистрации",
)
_LABEL_TIN = (
    "tax id",
    "taxpayer id",
    "tin",
    "հվհհ",
    "инн",
)
_LABEL_UNIQUE_ID = (
    "unique identifier",
    "եզակի նույնացուցիչ",
    "уникальный идентификатор",
)
_LABEL_ADDRESS = (
    "address",
    "հասցե",
    "адрес",
)
_LABEL_STATUS = (
    "company status",
    "status",
    "կարգավիճակ",
    "статус",
)
_LABEL_REGISTRAR = (
    "registration body",
    "գրանցող մարմին",
    "регистрирующий орган",
)

# The e-register card states status as a negative sentence ("no information
# recorded ... regarding liquidation or termination"), which means the company
# is active. This phrase must be checked before the inactive-token scan.
_STATUS_ACTIVE_PHRASES = (
    "no information recorded",
    "տեղեկություն առկա չէ",
    "нет сведений",
    "отсутствует информация",
)
_STATUS_ACTIVE_TOKENS = (
    "գործող",
    "ակտիվ",
    "գործում է",
    "active",
    "registered",
    "действующ",
    "активн",
)
_STATUS_INACTIVE_TOKENS = (
    "լուծարված",
    "դադարեցված",
    "սնանկ",
    "inactive",
    "liquidated",
    "in liquidation",
    "dissolved",
    "closed",
    "bankrupt",
    "terminat",
    "ликвидир",
    "прекращ",
    "закрыт",
    "недейств",
    "банкрот",
)


def _normalize_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("AM"):
        cleaned = cleaned[2:]
    if not _TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Armenia TIN (ՀՎՀՀ) must be exactly 8 digits, got: {value}"
        )
    return cleaned


def _normalize_reg_number(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip())
    if not cleaned or not _REG_NUM_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Armenia state-registry number invalid: {value}"
        )
    return cleaned


def _parse_am_date(value: str | None) -> date | None:
    """e-register renders dates as DD-MM-YYYY; tolerate dots, slashes, ISO."""
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(phrase in low for phrase in _STATUS_ACTIVE_PHRASES):
        return "active"
    if any(token in low for token in _STATUS_INACTIVE_TOKENS):
        return "inactive"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _legal_form_from_name(name: str) -> str | None:
    upper = name.upper()
    for suffix in _LEGAL_FORM_SUFFIXES:
        if re.search(rf"\b{suffix}\b", upper):
            return suffix
    return None


class AMAdapter(CountryAdapter):
    country_code = "AM"
    country_name = "Armenia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://e-register.moj.am"
    SEARCH_PATH = "/en/search/companies"
    COMPANY_PATH = "/en/companies"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en;q=0.9,hy;q=0.8,ru;q=0.6",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                hits = await self._search_hits(client, _HEALTH_PROBE_NAME)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        if not hits:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={
                    "search": True,
                    "lookup": True,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "e-register.moj.am responded but the probe query returned "
                    "no rows; page markup may have changed."
                ),
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={
                "search": True,
                "lookup": True,
                "financials": False,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + lookup live via e-register.moj.am. Filed financial "
                "statements are login-gated on the register; exchange and "
                "bulletin feeds are geo/Cloudflare-blocked outside Armenia."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with self._client() as client:
            hits = await self._search_hits(client, query)
            hits = hits[:limit]
            semaphore = asyncio.Semaphore(3)

            async def _guarded(uid: str) -> dict[str, Any]:
                async with semaphore:
                    return await self._fetch_record(client, uid)

            records = await asyncio.gather(
                *(_guarded(uid) for uid, _ in hits),
                return_exceptions=True,
            )

        matches: list[CompanyMatch] = []
        for (uid, hit_name), record in zip(hits, records):
            record = record if isinstance(record, dict) else {}
            tin = record.get("tin")
            reg = record.get("reg_number")
            identifiers = self._build_identifiers(tin, reg)
            matches.append(
                CompanyMatch(
                    id=tin or reg or uid,
                    name=record.get("name") or hit_name,
                    country=self.country_code,
                    identifiers=identifiers,
                    address=record.get("address"),
                    status=_classify_status(record.get("status_raw")),
                    source_url=f"{self.BASE_URL}{self.COMPANY_PATH}/{uid}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            wanted = _normalize_tin(value)
            field = "tin"
        elif id_type == IdentifierType.COMPANY_NUMBER:
            wanted = _normalize_reg_number(value)
            field = "reg_number"
        else:
            raise InvalidIdentifierError(
                "Armenia adapter only supports VAT (TIN) or COMPANY_NUMBER "
                f"(state-registry number), got {id_type}"
            )

        async with self._client() as client:
            hits = await self._search_hits(client, wanted)
            for uid, _ in hits[:10]:
                record = await self._fetch_record(client, uid)
                if not record:
                    continue
                found = record.get(field)
                if found and _same_identifier(found, wanted, field):
                    return self._to_details(record, uid)
        return None

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raise AdapterNotImplementedError(
            "No free financial-statements feed is reachable for Armenia from "
            "outside the country. Annual accounts filed with the State "
            "Register (e-register.moj.am) are login-gated; the Armenia "
            "Securities Exchange (amx.am) and Central Depository (cda.am) are "
            "Cloudflare IP-banned; the official bulletin (azdarar.am) and the "
            "Central Bank (cba.am) are geo-restricted to Armenia. Fetching "
            "real statements would require an Armenian egress or a registered "
            "account, so no data is fabricated here."
        )

    async def _search_hits(
        self, client: httpx.AsyncClient, query: str
    ) -> list[tuple[str, str]]:
        resp = await get_with_retry(
            client, self.SEARCH_PATH, params={"query": query}
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return _parse_search_hits(resp.text)

    async def _fetch_record(
        self, client: httpx.AsyncClient, unique_id: str
    ) -> dict[str, Any]:
        resp = await get_with_retry(
            client, f"{self.COMPANY_PATH}/{unique_id}"
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        record = _parse_company_card(resp.text)
        if record:
            record.setdefault("unique_id", unique_id)
        return record

    def _build_identifiers(
        self, tin: str | None, reg: str | None
    ) -> list[RegistryIdentifier]:
        identifiers: list[RegistryIdentifier] = []
        if tin:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=tin,
                    label="ՀՎՀՀ / TIN",
                )
            )
        if reg:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=reg,
                    label="State Registration Number",
                )
            )
        return identifiers

    def _to_details(
        self, record: dict[str, Any], unique_id: str
    ) -> CompanyDetails:
        tin = record.get("tin")
        reg = record.get("reg_number")
        name = record["name"]
        return CompanyDetails(
            id=tin or reg or unique_id,
            name=name,
            country=self.country_code,
            legal_form=_legal_form_from_name(name),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_am_date(record.get("registration_date")),
            registered_address=record.get("address"),
            identifiers=self._build_identifiers(tin, reg),
            raw={"source": "e-register.moj.am", "fields": record},
            source_url=f"{self.BASE_URL}{self.COMPANY_PATH}/{unique_id}",
        )


def _same_identifier(found: str, wanted: str, field: str) -> bool:
    if field == "tin":
        return re.sub(r"\D", "", found) == wanted
    return re.sub(r"\s+", "", found) == wanted


def _match_label(label: str, candidates: tuple[str, ...]) -> bool:
    low = label.lower().strip().rstrip(":").strip()
    return any(c in low for c in candidates)


def _clean_cell(fragment: str) -> str:
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


_ARTICLE_RE = re.compile(
    r'<article[^>]*class="[^"]*company-search-result[^"]*"[^>]*>(.*?)</article>',
    re.DOTALL,
)
_ARTICLE_LINK_RE = re.compile(
    r'href="/[a-z]{2}/companies/(\d+)"[^>]*>\s*<h[1-6][^>]*>(.*?)</h[1-6]>',
    re.DOTALL,
)
_DL_PAIR_RE = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.DOTALL)
_CARD_NAME_RE = re.compile(
    r'class="[^"]*company-title[^"]*"[^>]*>\s*<h[1-6][^>]*>(.*?)</h[1-6]>',
    re.DOTALL,
)


def _parse_search_hits(html: str) -> list[tuple[str, str]]:
    """Return ``(unique_id, name)`` pairs from a company search results page."""
    if not html:
        return []
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for block in _ARTICLE_RE.findall(html):
        m = _ARTICLE_LINK_RE.search(block)
        if not m:
            continue
        uid = m.group(1)
        if uid in seen:
            continue
        seen.add(uid)
        hits.append((uid, _clean_cell(m.group(2))))
    return hits


def _parse_company_card(html: str) -> dict[str, Any]:
    """Pull company fields out of an e-register.moj.am company card."""
    if not html:
        return {}
    record: dict[str, Any] = {}

    name_match = _CARD_NAME_RE.search(html)
    if name_match:
        candidate = _clean_cell(name_match.group(1))
        if candidate and "legal person" not in candidate.lower():
            record["name"] = candidate

    for label_html, value_html in _DL_PAIR_RE.findall(html):
        label = _clean_cell(label_html)
        value = _clean_cell(value_html)
        if not value:
            continue
        if "reg_number" not in record and _match_label(label, _LABEL_REG_NUMBER):
            record["reg_number"] = value
        elif "registration_date" not in record and _match_label(
            label, _LABEL_REG_DATE
        ):
            record["registration_date"] = value
        elif "tin" not in record and _match_label(label, _LABEL_TIN):
            digits = re.sub(r"\D", "", value)
            if _TIN_RE.match(digits):
                record["tin"] = digits
        elif "unique_id" not in record and _match_label(label, _LABEL_UNIQUE_ID):
            record["unique_id"] = re.sub(r"\D", "", value) or value
        elif "address" not in record and _match_label(label, _LABEL_ADDRESS):
            record["address"] = value
        elif "status_raw" not in record and _match_label(label, _LABEL_STATUS):
            record["status_raw"] = value
        elif "registrar" not in record and _match_label(label, _LABEL_REGISTRAR):
            record["registrar"] = value

    return record if record.get("name") else {}
