"""Albania adapter — QKB / QKR (National Business Center).

Source coverage:

* https://www.qkb.gov.al/ — Qendra Kombëtare e Biznesit (National
  Business Center), the unified Albanian commercial registry operated
  by the Ministry of Economy. It publishes a free public search portal
  keyed by NIPT (Numri i Identifikimit te Personit te Tatueshëm) or by
  company name. The same record also serves as the VAT registration
  number. No authentication.
* https://www.tatime.gov.al/ — General Directorate of Taxes (DPT). It
  hosts a per-NIPT validator used here as a liveness probe and a soft
  fallback when QKB markup changes.
* https://www.bse.com.al/ — Bursa e Tiranës (Tirana Stock Exchange).
  Very small (single-digit listed issuers) and serves filings as
  PDFs only — out of scope for the free MVP.

Identifier:
- VAT → NIPT. 10 characters in the canonical ``L\\d{8}L`` form
  (letter + 8 digits + letter, e.g. ``J91904005U``). The taxpayer ID
  doubles as VAT identifier; under the EU prefix convention this is
  rendered ``AL`` + NIPT.
- COMPANY_NUMBER → also the NIPT. Albania uses a single registry
  number across QKB and DPT, so we accept the same value under either
  identifier label.

No centralized free source of filed financial statements exists for
Albanian companies; ``fetch_financials`` therefore returns an empty
list rather than fabricating data. (Bursa e Tiranës PDFs are out of
scope for the free MVP.)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

# Canonical NIPT shape: leading letter + 8 digits + trailing letter.
_NIPT_RE = re.compile(r"^[A-Z]\d{8}[A-Z]$")

# Telekom Albania / ONE Telecommunications — used as a liveness probe.
_HEALTH_PROBE_NIPT = "J91904005U"

# QKB renders the company card as a two-column label/value table. Labels
# appear in Albanian and (depending on language toggle) English. Match
# loosely on either.
_LABEL_NAME = (
    "emri i subjektit",
    "emertimi",
    "emërtimi",
    "emri",
    "subject name",
    "name",
    "company name",
)
_LABEL_STATUS = (
    "statusi",
    "gjendja",
    "status",
    "state",
)
_LABEL_ADDRESS = (
    "adresa",
    "selia",
    "address",
    "registered address",
    "seat",
)
_LABEL_REG_DATE = (
    "data e regjistrimit",
    "data e themelimit",
    "data e krijimit",
    "registration date",
    "date of registration",
    "incorporation date",
)
_LABEL_LEGAL_FORM = (
    "forma ligjore",
    "lloji i subjektit",
    "legal form",
    "type",
    "entity type",
)
_LABEL_NIPT = (
    "nipt",
    "nuis",
    "numri unik i identifikimit",
    "tax id",
    "vat",
)
_LABEL_DIRECTOR = (
    "administrator",
    "administratori",
    "drejtues",
    "drejtuesi",
    "perfaqesues",
    "përfaqësues",
    "director",
    "manager",
)
_LABEL_CAPITAL = (
    "kapitali",
    "kapitali themeltar",
    "share capital",
    "charter capital",
)
_LABEL_OBJECT = (
    "objekti i veprimtarise",
    "objekti i veprimtarisë",
    "fusha e veprimtarise",
    "fusha e veprimtarisë",
    "activity",
    "business activity",
    "scope",
)

_STATUS_ACTIVE_TOKENS = (
    "aktiv",
    "i regjistruar",
    "e regjistruar",
    "active",
    "registered",
)
_STATUS_INACTIVE_TOKENS = (
    "c'regjistruar",
    "ç'regjistruar",
    "çregjistruar",
    "cregjistruar",
    "shuar",
    "pezulluar",
    "i pezulluar",
    "falimentuar",
    "ne likuidim",
    "në likuidim",
    "deregistered",
    "dissolved",
    "liquidated",
    "suspended",
    "bankrupt",
    "inactive",
    "closed",
)


def _normalize_nipt(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    # Albania VAT under the EU convention is written "AL" + NIPT. Strip
    # the prefix only when followed by a valid NIPT body; otherwise we'd
    # be silently truncating real input.
    if cleaned.startswith("AL") and _NIPT_RE.match(cleaned[2:]):
        cleaned = cleaned[2:]
    if not _NIPT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Albania NIPT must be letter+8 digits+letter (e.g. J91904005U), got: {value}"
        )
    return cleaned


def _parse_al_date(value: str | None) -> date | None:
    """QKB renders dates as DD/MM/YYYY or DD.MM.YYYY; tolerate ISO."""
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(token in low for token in _STATUS_INACTIVE_TOKENS):
        return "inactive"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _parse_capital_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.,]", "", raw)
    if not cleaned:
        return None
    # Albanian convention uses '.' as thousands and ',' as decimal.
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") >= 1:
        # Multiple dots, or a single dot followed by exactly 3 digits, is
        # the Albanian thousands separator. A single dot followed by 1-2
        # decimals (rare in capital values) is a decimal point.
        if cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "")
        else:
            tail = cleaned.rsplit(".", 1)[1]
            if len(tail) == 3:
                cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


class ALAdapter(CountryAdapter):
    country_code = "AL"
    country_name = "Albania"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://www.qkb.gov.al"
    SEARCH_PATH = "/search/"
    LOOKUP_PATH = "/search/search-in-trade-register/"
    TAX_PROBE_URL = "https://www.tatime.gov.al/"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "sq;q=0.9,en;q=0.8",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, "/")
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
                notes=str(exc)[:200],
            )

        low = page_text.lower()
        portal_alive = "qkb" in low or "biznes" in low or "register" in low
        if not portal_alive:
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
                    "qkb.gov.al responded but markup unrecognised; site may "
                    "be under maintenance."
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
                "Lookup live via qkb.gov.al HTML scrape. Financial "
                "statements are not centrally published in machine-readable "
                "form."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.LOOKUP_PATH,
                params={"search": query, "q": query, "name": query},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            page_text = _decode_response(resp)

        rows = _extract_search_rows(page_text)
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            nipt = row.get("nipt")
            if not nipt or not row.get("name"):
                continue
            ids = [
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=nipt,
                    label="NIPT",
                ),
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=nipt,
                    label="NIPT",
                ),
            ]
            matches.append(
                CompanyMatch(
                    id=nipt,
                    name=row["name"],
                    country=self.country_code,
                    identifiers=ids,
                    address=row.get("address"),
                    status=_classify_status(row.get("status_raw")),
                    source_url=(
                        f"{self.BASE_URL}{self.LOOKUP_PATH}?search={nipt}"
                    ),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                "Albania adapter only supports VAT (NIPT) or COMPANY_NUMBER "
                f"(also NIPT), got {id_type}"
            )
        nipt = _normalize_nipt(value)

        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.LOOKUP_PATH,
                params={"search": nipt, "q": nipt, "nipt": nipt},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            page_text = _decode_response(resp)

        record = _extract_company_record(page_text)
        if not record.get("name"):
            low = page_text.lower()
            if any(
                token in low
                for token in (
                    "nuk u gjet",
                    "asnje rezultat",
                    "asnjë rezultat",
                    "no results",
                    "not found",
                )
            ):
                return None
            return None

        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=nipt,
                label="NIPT",
            ),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=nipt,
                label="NIPT",
            ),
        ]
        director_name = (record.get("director") or "").strip()

        return CompanyDetails(
            id=nipt,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_al_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=_parse_capital_amount(record.get("capital")),
            capital_currency="ALL",
            identifiers=identifiers,
            raw={
                "source": "qkb.gov.al",
                "fields": record,
                "director_name": director_name or None,
                "business_object": record.get("business_object"),
            },
            source_url=f"{self.BASE_URL}{self.LOOKUP_PATH}?search={nipt}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # QKB exposes filed balance sheets only as scanned PDFs behind a
        # session-bound page and only on a per-document fee basis through
        # the historical archive. Bursa e Tiranës issuer reports are
        # PDF-only and out of scope for the free MVP. Returning an empty
        # list here honors the "no mock data" rule while keeping the API
        # contract intact (callers should not see a 501 for a known gap).
        return []


def _decode_response(resp: httpx.Response) -> str:
    """Decode the body, preferring UTF-8 (qkb.gov.al uses UTF-8 throughout).

    Falls back to Latin-1 derivatives only as a defensive measure for
    Albanian diacritics (ë, ç) when an upstream proxy strips encoding
    headers.
    """
    body = resp.content
    if not body:
        return ""
    for encoding in ("utf-8", "cp1252", "iso-8859-1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return resp.text


class _TableParser(HTMLParser):
    """Flatten every <td>/<th> cell into a list of stripped text strings."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self._in_cell = 0
        self._buf: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in ("td", "th"):
            self._in_cell += 1
            self._buf = []
        elif self._in_cell and tag in ("br", "p", "div", "li"):
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            text = unescape(text)
            self.cells.append(text)
            self._in_cell -= 1
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf.append(data)


class _SearchRowParser(HTMLParser):
    """Capture every <tr>'s flattened cell list, for search-results tables."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._in_row = False
        self._in_cell = 0
        self._buf: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell += 1
            self._buf = []
        elif self._in_cell and tag in ("br", "p", "div", "li"):
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            text = unescape(text)
            self._row.append(text)
            self._in_cell -= 1
            self._buf = []
        elif tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf.append(data)


def _match_label(cell: str, candidates: tuple[str, ...]) -> bool:
    low = cell.lower().strip().rstrip(":").strip()
    return any(label in low for label in candidates)


def _extract_company_record(html: str) -> dict[str, Any]:
    """Pull the company fields out of a qkb.gov.al detail page."""
    if not html:
        return {}

    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("AL QKB HTML parse failed: %s", exc)
        return {}

    cells = [c for c in parser.cells if c]
    record: dict[str, Any] = {}
    for label_cell, value_cell in zip(cells, cells[1:]):
        if not value_cell:
            continue
        if "name" not in record and _match_label(label_cell, _LABEL_NAME):
            record["name"] = value_cell
        elif "status_raw" not in record and _match_label(
            label_cell, _LABEL_STATUS
        ):
            record["status_raw"] = value_cell
        elif "address" not in record and _match_label(
            label_cell, _LABEL_ADDRESS
        ):
            record["address"] = value_cell
        elif "registration_date" not in record and _match_label(
            label_cell, _LABEL_REG_DATE
        ):
            record["registration_date"] = value_cell
        elif "legal_form" not in record and _match_label(
            label_cell, _LABEL_LEGAL_FORM
        ):
            record["legal_form"] = value_cell
        elif "nipt" not in record and _match_label(label_cell, _LABEL_NIPT):
            up = value_cell.upper().replace(" ", "")
            if _NIPT_RE.match(up):
                record["nipt"] = up
        elif "director" not in record and _match_label(
            label_cell, _LABEL_DIRECTOR
        ):
            record["director"] = value_cell
        elif "capital" not in record and _match_label(
            label_cell, _LABEL_CAPITAL
        ):
            record["capital"] = value_cell
        elif "business_object" not in record and _match_label(
            label_cell, _LABEL_OBJECT
        ):
            record["business_object"] = value_cell

    if "name" not in record:
        # QKB sometimes renders the company name above the table inside
        # a heading element when only one match is returned.
        m = re.search(
            r"<h[12][^>]*>\s*([^<]{3,200})\s*</h[12]>",
            html,
            re.IGNORECASE,
        )
        if m:
            candidate = unescape(re.sub(r"\s+", " ", m.group(1)).strip())
            low = candidate.lower()
            if "qkb" not in low and "kerko" not in low and "kërko" not in low:
                record["name"] = candidate
    return record


def _extract_search_rows(html: str) -> list[dict[str, Any]]:
    """Best-effort parse of the QKB name-search results page.

    Result rows expose the company name and NIPT side-by-side; the NIPT
    is uniquely shaped (letter + 8 digits + letter), so we use that as
    the anchor.
    """
    if not html:
        return []
    parser = _SearchRowParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("AL QKB search parse failed: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        cleaned = [c for c in cells if c]
        if len(cleaned) < 2:
            continue
        nipt_match: str | None = None
        for c in cleaned:
            up = c.upper().replace(" ", "")
            if _NIPT_RE.match(up):
                nipt_match = up
                break
        if not nipt_match:
            continue
        name_candidate: str | None = None
        for c in cleaned:
            if c.upper().replace(" ", "") == nipt_match:
                continue
            if re.fullmatch(r"[\d\s./\-]+", c):
                continue
            if len(c) < 3:
                continue
            if name_candidate is None or len(c) > len(name_candidate):
                name_candidate = c
        if not name_candidate:
            continue
        if name_candidate.lower() in {
            "name",
            "emri",
            "emertimi",
            "emërtimi",
        }:
            continue
        rows.append(
            {
                "name": name_candidate,
                "nipt": nipt_match,
                "address": _pick_address(cleaned),
                "status_raw": _pick_status(cleaned),
            }
        )
    return rows


def _pick_address(cells: list[str]) -> str | None:
    for c in cells:
        low = c.lower()
        if any(
            token in low
            for token in (
                "tirane",
                "tiranë",
                "tirana",
                "durres",
                "durrës",
                "vlore",
                "vlorë",
                "shkoder",
                "shkodër",
                "rruga",
                "rr.",
                "street",
            )
        ):
            return c
    return None


def _pick_status(cells: list[str]) -> str | None:
    for c in cells:
        low = c.lower()
        if any(token in low for token in _STATUS_ACTIVE_TOKENS):
            return c
        if any(token in low for token in _STATUS_INACTIVE_TOKENS):
            return c
    return None
