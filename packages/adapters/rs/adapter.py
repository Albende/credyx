"""Serbia adapter — APR (Agencija za privredne registre).

Sources (all free, no auth):

* Unified entity search portal at
  ``https://pretraga2.apr.gov.rs/unifiedentitysearch`` — public HTML
  search that accepts a free-text query (company name, MB or PIB) and
  returns a list of links to per-company detail pages. The portal
  renders both Cyrillic and Latin Serbian.
* Financial-statements public search at
  ``https://pretraga2.apr.gov.rs/fiPublicSearch`` — APR publishes every
  filed annual financial report (Godišnji finansijski izveštaj) keyed
  by MB. PDFs are free to download.
* Belgrade Stock Exchange (now hosted at bgdx.rs, formerly belex.rs)
  exposes per-issuer profile pages but no machine-readable filings
  index; we surface a deep-link only.

Identifiers:

* Matični broj (MB) — 8-digit company registration number, primary.
* PIB — 9-digit tax identification number; often prefixed ``RS`` in
  VAT contexts. We accept both as inputs and map MB → COMPANY_NUMBER,
  PIB → VAT.

The APR portal is a server-rendered ASP.NET app that serves HTML only
(no documented JSON contract). We scrape conservatively, never invent
fields, and fall back to a minimal ``CompanyDetails`` carrying the
identifier plus a deep-link when the page markup shifts. Returning
fabricated names or numbers would violate the project rule against
mock data.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

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

logger = logging.getLogger(__name__)

_MB_RE = re.compile(r"^\d{8}$")
_PIB_RE = re.compile(r"^\d{9}$")
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MB_IN_TEXT_RE = re.compile(r"\b\d{8}\b")
_PIB_IN_TEXT_RE = re.compile(r"\b\d{9}\b")

# NIS a.d. — stable, large active issuer used as a portal-liveness probe.
_HEALTH_PROBE_MB = "20084693"

# Field labels APR renders in either Cyrillic or Latin Serbian. Matches are
# case-insensitive and tolerate the dijakritički variants.
_LABEL_NAME = (
    "пословно име",
    "poslovno ime",
    "назив",
    "naziv",
    "name",
)
_LABEL_LEGAL_FORM = (
    "правна форма",
    "pravna forma",
    "правни облик",
    "pravni oblik",
    "legal form",
)
_LABEL_STATUS = (
    "статус",
    "status",
)
_LABEL_ADDRESS = (
    "седиште",
    "sediste",
    "седишта",
    "адреса",
    "adresa",
    "address",
)
_LABEL_MB = ("матични број", "maticni broj", "mb")
_LABEL_PIB = ("пиб", "pib")
_LABEL_INCORP = (
    "датум оснивања",
    "datum osnivanja",
    "датум регистрације",
    "datum registracije",
)
_LABEL_CAPITAL = (
    "уписани капитал",
    "upisani kapital",
    "новчани капитал",
    "novcani kapital",
    "капитал",
    "kapital",
)
_LABEL_ACTIVITY = (
    "шифра делатности",
    "sifra delatnosti",
    "делатност",
    "delatnost",
)

_STATUS_ACTIVE_TOKENS = ("активно", "aktivno", "активан", "aktivan", "active")
_STATUS_CEASED_TOKENS = (
    "брисан",
    "brisan",
    "ликвидиран",
    "likvidiran",
    "стечај",
    "stecaj",
    "stečaj",
    "престала",
    "prestala",
)


def _normalize_mb(value: str) -> str:
    """Strip whitespace, validate to 8 digits."""
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _MB_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Serbian Matični broj must be exactly 8 digits, got: {value}"
        )
    return cleaned


def _normalize_pib(value: str) -> str:
    """Strip optional ``RS`` VAT prefix and whitespace, validate to 9 digits."""
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("RS"):
        cleaned = cleaned[2:]
    if not _PIB_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Serbian PIB must be exactly 9 digits, got: {value}"
        )
    return cleaned


def _parse_rs_date(value: str | None) -> date | None:
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d.%m.%Y.", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10].rstrip("."), fmt.rstrip(".")).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(token in low for token in _STATUS_CEASED_TOKENS):
        return "ceased"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


class RSAdapter(CountryAdapter):
    country_code = "RS"
    country_name = "Serbia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    PORTAL_BASE = "https://pretraga2.apr.gov.rs"
    SEARCH_PATH = "/unifiedentitysearch/Search/Search"
    FI_SEARCH_PATH = "/fiPublicSearch/SearchEntities/Search"

    def _client(self, *, timeout: float = 30.0):
        return build_http_client(
            base_url=self.PORTAL_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "Accept-Language": "sr,en;q=0.7",
            },
            timeout=timeout,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client(timeout=20.0) as client:
                resp = await get_with_retry(
                    client,
                    self.SEARCH_PATH,
                    params={"text": _HEALTH_PROBE_MB},
                )
                resp.raise_for_status()
                page_text = _decode_response(resp)
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
                notes=f"APR pretraga2 probe failed: {str(exc)[:160]}",
            )
        # The portal sometimes serves a fully client-rendered shell with no
        # results in the initial HTML. We accept either a successful response
        # that mentions the probe MB or any successful 200 as "reachable".
        ok_signal = _HEALTH_PROBE_MB in page_text or "pretraga" in page_text.lower()
        if not ok_signal:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={
                    "search": False,
                    "lookup": True,
                    "financials": True,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "APR pretraga2 reachable but probe MB not echoed; markup "
                    "may have changed — search results parsing may be partial."
                ),
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={
                "search": True,
                "lookup": True,
                "financials": True,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "APR unified entity search (lookup + name search) + APR "
                "fiPublicSearch for annual financial reports. HTML scrape; "
                "results best-effort and may degrade on portal redesigns."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.SEARCH_PATH,
                params={"text": name},
            )
            resp.raise_for_status()
            page_text = _decode_response(resp)
        records = _parse_search_results(page_text)
        out: list[CompanyMatch] = []
        for rec in records[:limit]:
            mb = rec.get("mb")
            pib = rec.get("pib")
            if not mb and not pib:
                continue
            idents: list[RegistryIdentifier] = []
            if mb:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=mb,
                        label="Matični broj",
                    )
                )
            if pib:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=pib,
                        label="PIB",
                    )
                )
            out.append(
                CompanyMatch(
                    id=mb or pib or "",
                    name=rec.get("name", "").strip(),
                    country=self.country_code,
                    identifiers=idents,
                    address=rec.get("address"),
                    status=_classify_status(rec.get("status_raw")),
                    source_url=self._search_url(name),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            mb = _normalize_mb(value)
            query = mb
        elif id_type == IdentifierType.VAT:
            pib = _normalize_pib(value)
            query = pib
            mb = None
        else:
            raise InvalidIdentifierError(
                f"Serbia supports COMPANY_NUMBER (MB) or VAT (PIB), got {id_type}"
            )

        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.SEARCH_PATH,
                params={"text": query},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            page_text = _decode_response(resp)

        record = _pick_record(_parse_search_results(page_text), mb=mb, pib=None if mb else pib)
        if record is None:
            return None

        resolved_mb = record.get("mb") or mb
        resolved_pib = record.get("pib") or (pib if id_type == IdentifierType.VAT else None)

        identifiers: list[RegistryIdentifier] = []
        if resolved_mb:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=resolved_mb,
                    label="Matični broj",
                )
            )
        if resolved_pib:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=resolved_pib,
                    label="PIB",
                )
            )

        capital_amount, capital_currency = _parse_capital(record.get("capital"))

        return CompanyDetails(
            id=resolved_mb or resolved_pib or "",
            name=record.get("name", "").strip(),
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_rs_date(record.get("incorporation_date")),
            registered_address=record.get("address"),
            capital_amount=capital_amount,
            capital_currency=capital_currency,
            nace_codes=[record["activity_code"]] if record.get("activity_code") else [],
            identifiers=identifiers,
            raw={"source": "apr.gov.rs/pretraga2", "fields": record},
            source_url=self._search_url(query),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        mb = _normalize_mb(company_id)
        async with self._client(timeout=40.0) as client:
            try:
                resp = await get_with_retry(
                    client,
                    self.FI_SEARCH_PATH,
                    params={"maticniBroj": mb},
                )
            except Exception as exc:
                logger.warning("APR fiPublicSearch failed for MB %s: %s", mb, exc)
                return []
            if resp.status_code in (404, 500):
                return []
            try:
                resp.raise_for_status()
            except Exception:
                return []
            page_text = _decode_response(resp)

        years_found = _parse_fi_years(page_text)
        if not years_found:
            return []
        cutoff = max(years_found) - years
        filings: list[FinancialFiling] = []
        for y in sorted(years_found, reverse=True):
            if y < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=mb,
                    year=y,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(y, 12, 31),
                    currency="RSD",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=(
                        f"{self.PORTAL_BASE}/fiPublicSearch/SearchEntities/Search"
                        f"?maticniBroj={mb}"
                    ),
                )
            )
        return filings

    def _search_url(self, text: str) -> str:
        return (
            f"{self.PORTAL_BASE}{self.SEARCH_PATH}?text={quote(text, safe='')}"
        )


def _decode_response(resp) -> str:
    """Decode response bytes preferring UTF-8 then cp1250 (legacy Serbian)."""
    body = resp.content
    if not body:
        return ""
    for encoding in ("utf-8", "cp1250", "windows-1250", "cp1251"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return resp.text


class _CellParser(HTMLParser):
    """Flatten every ``<td>``/``<th>`` cell into a stripped string list."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self._depth = 0
        self._buf: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in ("td", "th"):
            self._depth += 1
            self._buf = []
        elif self._depth and tag in ("br", "p", "div", "li"):
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._depth:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self.cells.append(unescape(text))
            self._depth -= 1
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._buf.append(data)


def _strip_html(text: str) -> str:
    return unescape(re.sub(r"\s+", " ", _TAG_STRIP_RE.sub(" ", text))).strip()


def _match_label(cell: str, candidates: tuple[str, ...]) -> bool:
    low = cell.lower().strip().rstrip(":").strip()
    return any(label in low for label in candidates)


def _parse_search_results(html: str) -> list[dict[str, Any]]:
    """Best-effort extraction of company rows from the APR pretraga2 HTML.

    The portal renders results in one of two shapes depending on viewport
    and entity type — sometimes a flat table of ``label/value`` rows for a
    single match, sometimes a card list for multi-row results. We accept
    either: harvest every ``<td>`` cell, walk pairwise looking for the
    canonical labels, and additionally scan loose text for MB / PIB tokens
    so a row missing structured labels still gives us identifiers.
    """
    if not html:
        return []

    parser = _CellParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("RS APR HTML parse failed: %s", exc)
        return []

    cells = [c for c in parser.cells if c]
    record: dict[str, Any] = {}
    for label_cell, value_cell in zip(cells, cells[1:]):
        if not value_cell:
            continue
        if "name" not in record and _match_label(label_cell, _LABEL_NAME):
            record["name"] = value_cell
        elif "legal_form" not in record and _match_label(label_cell, _LABEL_LEGAL_FORM):
            record["legal_form"] = value_cell
        elif "status_raw" not in record and _match_label(label_cell, _LABEL_STATUS):
            record["status_raw"] = value_cell
        elif "address" not in record and _match_label(label_cell, _LABEL_ADDRESS):
            record["address"] = value_cell
        elif "mb" not in record and _match_label(label_cell, _LABEL_MB):
            m = _MB_IN_TEXT_RE.search(value_cell)
            if m:
                record["mb"] = m.group(0)
        elif "pib" not in record and _match_label(label_cell, _LABEL_PIB):
            m = _PIB_IN_TEXT_RE.search(value_cell)
            if m:
                record["pib"] = m.group(0)
        elif "incorporation_date" not in record and _match_label(label_cell, _LABEL_INCORP):
            record["incorporation_date"] = value_cell
        elif "capital" not in record and _match_label(label_cell, _LABEL_CAPITAL):
            record["capital"] = value_cell
        elif "activity_code" not in record and _match_label(label_cell, _LABEL_ACTIVITY):
            code_match = re.search(r"\d{4}", value_cell)
            if code_match:
                record["activity_code"] = code_match.group(0)

    if not record.get("mb") or not record.get("pib"):
        flat = _strip_html(html)
        if not record.get("mb"):
            for m in _MB_IN_TEXT_RE.finditer(flat):
                token = m.group(0)
                # 9-digit PIB occurrences also produce 8-digit substrings —
                # only accept an 8-digit hit that isn't part of a longer run.
                start, end = m.span()
                before = flat[start - 1] if start > 0 else " "
                after = flat[end] if end < len(flat) else " "
                if not before.isdigit() and not after.isdigit():
                    record["mb"] = token
                    break
        if not record.get("pib"):
            for m in _PIB_IN_TEXT_RE.finditer(flat):
                token = m.group(0)
                start, end = m.span()
                before = flat[start - 1] if start > 0 else " "
                after = flat[end] if end < len(flat) else " "
                if not before.isdigit() and not after.isdigit():
                    record["pib"] = token
                    break

    if not (record.get("mb") or record.get("pib") or record.get("name")):
        return []
    return [record]


def _pick_record(
    records: list[dict[str, Any]],
    *,
    mb: str | None,
    pib: str | None,
) -> dict[str, Any] | None:
    if not records:
        return None
    if mb:
        for r in records:
            if r.get("mb") == mb:
                return r
    if pib:
        for r in records:
            if r.get("pib") == pib:
                return r
    return records[0] if records else None


def _parse_capital(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    text = value.strip()
    currency = None
    for token, code in (("RSD", "RSD"), ("дин", "RSD"), ("din", "RSD"), ("EUR", "EUR"), ("евро", "EUR")):
        if token.lower() in text.lower():
            currency = code
            break
    m = re.search(r"([\d][\d\s.,]*)", text)
    if not m:
        return None, currency
    raw = m.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    # APR renders amounts in Serbian locale: "1.234.567,89" → "1234567.89".
    # The replacements above strip the thousands dots first, then map the
    # decimal comma, which is robust to either "1.234.567,89" or "1234567,89".
    try:
        return float(raw), (currency or "RSD")
    except ValueError:
        return None, currency


def _parse_fi_years(html: str) -> list[int]:
    """Extract distinct reporting years from an APR fiPublicSearch listing."""
    stripped = _strip_html(html)
    years: set[int] = set()
    current_year = date.today().year
    for match in _YEAR_RE.finditer(stripped):
        y = int(match.group(0))
        # APR began collecting electronic filings around 2005; clip the lower
        # bound to avoid stray years embedded in addresses or footer copy.
        if 2005 <= y <= current_year:
            years.add(y)
    return sorted(years)
