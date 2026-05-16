"""Germany adapter — OffeneRegister.de (free Handelsregister mirror) + Bundesanzeiger.

Why this design:
- handelsregister.de itself is web-only, session-bound, and charges €1 per
  filing document. We skip it per the MVP "no paid APIs" rule.
- OffeneRegister.de provides a free JSON API mirroring the Handelsregister:
  search by name, fetch a slugged detail record including HRB number and
  the registering court (Amtsgericht).
- Bundesanzeiger publishes "Jahresabschluss" filings as free public XBRL/PDF
  documents but exposes no JSON API. For `fetch_financials` we attempt a
  best-effort HTML scrape of the public search page; if the structure
  changes, we surface zero filings instead of crashing so the LLM pipeline
  can still run on registry data alone.

Identifiers:
- HRB number (e.g. "HRB 42243") with an Amtsgericht prefix is the canonical
  Handelsregister identifier; we accept it with or without the court name.
- COMPANY_NUMBER is accepted as an alias (OffeneRegister slug).
- VAT (USt-IdNr, "DE" + 9 digits) is recognised but currently mapped via
  name-search fallback because OffeneRegister has no VAT lookup endpoint.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_HRB_RE = re.compile(r"^HR[BA]\s*\d+$", re.IGNORECASE)
_HRB_NUMERIC_RE = re.compile(r"HR[BA]\s*(\d+)", re.IGNORECASE)
_VAT_RE = re.compile(r"^DE\d{9}$", re.IGNORECASE)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]+$")


class DEAdapter(CountryAdapter):
    country_code = "DE"
    country_name = "Germany"
    identifier_types = [
        IdentifierType.HRB,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.VAT,
    ]
    primary_identifier = IdentifierType.HRB
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://offeneregister.de"
    BUNDESANZEIGER_URL = "https://www.bundesanzeiger.de"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(
                    client, "/api/v1/companies", params={"name": "siemens", "size": 1}
                )
                if resp.status_code >= 500:
                    raise AdapterError(f"OffeneRegister {resp.status_code}")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"OffeneRegister unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "Registry: OffeneRegister.de (free). Financials: Bundesanzeiger "
                "best-effort scrape; may return [] if structure changes."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        items = await self._or_search(name, limit)
        matches: list[CompanyMatch] = []
        for item in items[:limit]:
            slug = item.get("slug") or item.get("id")
            if not slug:
                continue
            matches.append(_match_from_or_item(item, slug))
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        cleaned = value.strip()
        if id_type == IdentifierType.COMPANY_NUMBER:
            slug = _normalize_slug(cleaned)
            return await self._or_detail_by_slug(slug)

        if id_type == IdentifierType.HRB:
            return await self._lookup_by_hrb(cleaned)

        if id_type == IdentifierType.VAT:
            vat = cleaned.upper().replace(" ", "")
            if not _VAT_RE.match(vat):
                raise InvalidIdentifierError(
                    f"German VAT must be DE + 9 digits: {value}"
                )
            return await self._lookup_by_vat(vat)

        raise InvalidIdentifierError(
            f"DE supports HRB, COMPANY_NUMBER (slug), VAT — got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        details = await self._or_detail_by_slug(_normalize_slug(company_id))
        if details is None:
            return []
        try:
            return await self._scrape_bundesanzeiger(details, years)
        except Exception:
            return []

    async def _or_search(self, name: str, limit: int) -> list[dict[str, Any]]:
        size = max(1, min(int(limit), 50))
        async with build_http_client(base_url=self.BASE_URL) as client:
            try:
                resp = await get_with_retry(
                    client, "/api/v1/companies", params={"name": name, "size": size}
                )
            except Exception as exc:
                raise AdapterError(f"OffeneRegister request failed: {exc}") from exc
        if resp.status_code >= 500:
            raise AdapterError(
                f"OffeneRegister returned {resp.status_code} for name search"
            )
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code == 404:
            if "json" in ctype:
                return []
            raise AdapterError(
                "OffeneRegister name-search returned 404 with non-JSON body — "
                "API may be offline or the path moved."
            )
        resp.raise_for_status()
        if "json" not in ctype:
            raise AdapterError(
                "OffeneRegister returned non-JSON response — service may be "
                "offline or the API path moved."
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AdapterError(f"OffeneRegister returned malformed JSON: {exc}") from exc
        return _extract_or_items(payload)

    async def _or_detail_by_slug(self, slug: str) -> CompanyDetails | None:
        async with build_http_client(base_url=self.BASE_URL) as client:
            try:
                resp = await get_with_retry(client, f"/api/v1/company/{slug}")
            except Exception as exc:
                raise AdapterError(f"OffeneRegister detail failed: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 500:
            raise AdapterError(f"OffeneRegister returned {resp.status_code}")
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" not in ctype:
            raise AdapterError(
                "OffeneRegister detail returned non-JSON — service may be offline."
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise AdapterError(f"OffeneRegister malformed JSON: {exc}") from exc
        return _details_from_or_payload(data, slug)

    async def _lookup_by_hrb(self, raw: str) -> CompanyDetails | None:
        m = _HRB_NUMERIC_RE.search(raw)
        if not m:
            raise InvalidIdentifierError(
                f"Expected HRB <number> [court], got: {raw}"
            )
        hrb_number = m.group(1)
        court = raw[m.end():].strip().strip(",.;-")
        query = f"HRB {hrb_number} {court}".strip()

        items = await self._or_search(query, limit=20)
        target = _select_by_hrb(items, hrb_number, court)
        if target is None:
            items = await self._or_search(f"HRB {hrb_number}", limit=20)
            target = _select_by_hrb(items, hrb_number, court)
        if target is None:
            return None
        slug = target.get("slug") or target.get("id")
        if not slug:
            return None
        details = await self._or_detail_by_slug(_normalize_slug(str(slug)))
        return details

    async def _lookup_by_vat(self, vat: str) -> CompanyDetails | None:
        items = await self._or_search(vat, limit=5)
        for item in items:
            if _vat_matches(item, vat):
                slug = item.get("slug") or item.get("id")
                if slug:
                    return await self._or_detail_by_slug(_normalize_slug(str(slug)))
        return None

    async def _scrape_bundesanzeiger(
        self, details: CompanyDetails, years: int
    ) -> list[FinancialFiling]:
        search_url = (
            f"{self.BUNDESANZEIGER_URL}/pub/en/start?0-1.-top%7Eheader%7Esearchbar"
            f"~form-search_word_input=" + quote_plus(details.name)
        )
        async with build_http_client(base_url=self.BUNDESANZEIGER_URL) as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/pub/en/start",
                    params={"globalsearch_keyword": details.name},
                )
            except Exception:
                return []
        if resp.status_code != 200 or not resp.text:
            return []

        rows = _parse_bundesanzeiger_results(resp.text, details.name)
        cutoff_year = datetime.utcnow().year - years
        filings: list[FinancialFiling] = []
        for row in rows:
            if row["year"] < cutoff_year:
                continue
            filings.append(
                FinancialFiling(
                    company_id=details.id,
                    year=row["year"],
                    type=FilingType.ANNUAL_REPORT,
                    period_end=row["period_end"],
                    currency="EUR",
                    structured_data=None,
                    document_url=row.get("document_url"),
                    document_format=row.get("document_format", "html"),
                    source_url=search_url,
                )
            )
        return filings


def _extract_or_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("results", "items", "data", "hits", "companies"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _normalize_slug(value: str) -> str:
    s = value.strip().lower()
    if not _SLUG_RE.match(s):
        raise InvalidIdentifierError(f"Not a valid OffeneRegister slug: {value}")
    return s


def _match_from_or_item(item: dict[str, Any], slug: str) -> CompanyMatch:
    hrb = _hrb_from_item(item)
    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=str(slug),
            label="OffeneRegister slug",
        ),
    ]
    if hrb:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.HRB, value=hrb, label="HRB")
        )
    vat = item.get("vat_id") or item.get("vatId")
    if vat:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.VAT, value=str(vat), label="USt-IdNr")
        )
    return CompanyMatch(
        id=str(slug),
        name=_pick_name(item),
        country="DE",
        identifiers=identifiers,
        address=_address_from_item(item),
        status=_status_from_item(item),
        source_url=f"https://offeneregister.de/company/{slug}",
    )


def _details_from_or_payload(data: dict[str, Any], slug: str) -> CompanyDetails:
    hrb = _hrb_from_item(data)
    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=slug, label="OffeneRegister slug"
        ),
    ]
    if hrb:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.HRB, value=hrb, label="HRB")
        )
    vat = data.get("vat_id") or data.get("vatId")
    if vat:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.VAT, value=str(vat), label="USt-IdNr")
        )

    capital_raw = data.get("capital") or data.get("capital_amount")
    capital = _coerce_float(capital_raw)
    capital_currency = data.get("capital_currency") or ("EUR" if capital else None)

    return CompanyDetails(
        id=slug,
        name=_pick_name(data),
        country="DE",
        legal_form=data.get("legal_form") or data.get("legalForm"),
        status=_status_from_item(data),
        incorporation_date=_parse_date(
            data.get("incorporation_date") or data.get("registration_date")
        ),
        dissolution_date=_parse_date(data.get("dissolution_date")),
        registered_address=_address_from_item(data),
        capital_amount=capital,
        capital_currency=capital_currency,
        identifiers=identifiers,
        directors=[],
        shareholders=[],
        raw=data,
        source_url=f"https://offeneregister.de/company/{slug}",
    )


def _pick_name(item: dict[str, Any]) -> str:
    for key in ("name", "current_name", "company_name", "title"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    names = item.get("all_names") or item.get("previous_names")
    if isinstance(names, list) and names:
        first = names[0]
        if isinstance(first, dict):
            return str(first.get("name", "")).strip()
        if isinstance(first, str):
            return first.strip()
    return ""


def _hrb_from_item(item: dict[str, Any]) -> str | None:
    reg_no = (
        item.get("native_company_number")
        or item.get("registerNumber")
        or item.get("register_number")
        or item.get("companyId")
        or item.get("company_id")
    )
    art = (item.get("registerArt") or item.get("register_art") or "").strip()
    court = (
        item.get("registerCourt")
        or item.get("register_court")
        or item.get("registrar")
        or ""
    ).strip()
    if reg_no:
        prefix = art.upper() if art.upper() in ("HRB", "HRA") else "HRB"
        digits = re.sub(r"\D", "", str(reg_no))
        if digits:
            base = f"{prefix} {digits}"
            return f"{base} {court}".strip() if court else base
    raw = item.get("hrb") or item.get("HRB")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _address_from_item(item: dict[str, Any]) -> str | None:
    addr = item.get("registered_office") or item.get("address") or item.get("addr")
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            addr.get("street"),
            addr.get("house_number"),
            addr.get("postal_code") or addr.get("postcode"),
            addr.get("city") or addr.get("locality"),
        ]
        s = " ".join(str(p) for p in parts if p)
        if s.strip():
            return s.strip()
    city = item.get("city") or item.get("registered_city")
    if isinstance(city, str) and city.strip():
        return city.strip()
    return None


def _status_from_item(item: dict[str, Any]) -> str | None:
    status = item.get("status") or item.get("company_status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    if item.get("dissolution_date"):
        return "ceased"
    return "active"


def _select_by_hrb(
    items: list[dict[str, Any]], hrb_number: str, court: str
) -> dict[str, Any] | None:
    court_norm = _normalize_court(court)
    candidates_exact: list[dict[str, Any]] = []
    candidates_number_only: list[dict[str, Any]] = []
    for item in items:
        item_hrb = _hrb_from_item(item) or ""
        m = _HRB_NUMERIC_RE.search(item_hrb)
        if not m:
            continue
        if m.group(1) != hrb_number:
            continue
        item_court = _normalize_court(
            (item.get("registerCourt") or item.get("register_court") or "")
        )
        if court_norm and item_court and court_norm in item_court:
            candidates_exact.append(item)
        else:
            candidates_number_only.append(item)
    if candidates_exact:
        return candidates_exact[0]
    if candidates_number_only:
        return candidates_number_only[0]
    return None


def _normalize_court(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def _vat_matches(item: dict[str, Any], vat: str) -> bool:
    item_vat = item.get("vat_id") or item.get("vatId")
    if isinstance(item_vat, str):
        return item_vat.upper().replace(" ", "") == vat
    return False


def _parse_date(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class _BAResultsParser(HTMLParser):
    """Pulls anchor texts + hrefs out of Bundesanzeiger HTML.

    Bundesanzeiger renders search results as a table where each row links to
    a publication. We don't try to fully understand the DOM — we scan for
    anchors whose text mentions "Jahresabschluss"/"Annual Report" and pair
    them with the nearest 4-digit year token in the surrounding text. If the
    site rearranges its markup, we naturally fall back to an empty list.
    """

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self.text_buffer: list[str] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            self._current_href = href
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            text = "".join(self._current_text).strip()
            if text:
                self.anchors.append((text, self._current_href))
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)
        self.text_buffer.append(data)


def _parse_bundesanzeiger_results(
    html: str, company_name: str
) -> list[dict[str, Any]]:
    parser = _BAResultsParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    name_norm = re.sub(r"\W", "", company_name.lower())
    full_text = " ".join(parser.text_buffer)
    if name_norm and re.sub(r"\W", "", full_text.lower()).find(name_norm) < 0:
        return []

    year_re = re.compile(r"\b(19|20)\d{2}\b")
    relevant = ("jahresabschluss", "annual report", "konzernabschluss")
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for text, href in parser.anchors:
        low = text.lower()
        if not any(token in low for token in relevant):
            continue
        m = year_re.search(text)
        if not m:
            continue
        year = int(m.group(0))
        url = href
        if url.startswith("/"):
            url = "https://www.bundesanzeiger.de" + url
        key = (year, url)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "year": year,
                "period_end": date(year, 12, 31),
                "document_url": url,
                "document_format": "pdf" if url.lower().endswith(".pdf") else "html",
            }
        )
    out.sort(key=lambda x: x["year"], reverse=True)
    return out
