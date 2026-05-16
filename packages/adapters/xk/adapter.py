"""Kosovo adapter — ARBK (Agjencia për Regjistrimin e Bizneseve të Kosovës).

Source: https://arbk.rks-gov.net/ — the Kosovo Business Registration Agency
operates the public free portal. Search by business name or by the
unique business number. No API key, no auth.

Identifier:
- COMPANY_NUMBER → Numri Unik i Biznesit (UBI / NRB), 8 digits + 1
  trailing letter (e.g. ``70123456A``). Some historical entities also
  carry a 9-digit fiscal/VAT number (NF). Both identifier shapes are
  accepted.
- VAT → Numri Fiskal (NF), 9 digits in the canonical form ``\\d{9}``.
  Under the EU VAT prefix convention this is rendered ``XK`` + NF — the
  adapter strips that prefix when present.

ARBK does not publish filed annual accounts in machine-readable form;
``fetch_financials`` returns ``[]`` rather than fabricate data. Filings
of audited statements live with the Kosovo Financial Reporting Council
(KKRF / KCFR) but are exposed only as scanned PDFs behind a
session-bound page — out of scope for the free MVP.
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

_UBI_RE = re.compile(r"^\d{8}[A-Z]$")
_NF_RE = re.compile(r"^\d{9}$")

# ARBK card labels appear in Albanian, Serbian, and English depending on
# the language toggle. Match loosely on either.
_LABEL_NAME = (
    "emri i biznesit",
    "emri",
    "emertimi",
    "emërtimi",
    "naziv",
    "business name",
    "name",
)
_LABEL_STATUS = (
    "statusi",
    "gjendja",
    "status",
    "stanje",
    "state",
)
_LABEL_ADDRESS = (
    "adresa",
    "selia",
    "adresa e selisë",
    "adresa e selise",
    "adresa selia",
    "address",
    "registered address",
    "sedište",
    "sediste",
)
_LABEL_REG_DATE = (
    "data e regjistrimit",
    "data e themelimit",
    "data e krijimit",
    "datum registracije",
    "registration date",
    "date of registration",
    "incorporation date",
)
_LABEL_LEGAL_FORM = (
    "forma e biznesit",
    "forma ligjore",
    "lloji i biznesit",
    "lloji i subjektit",
    "pravna forma",
    "legal form",
    "business type",
    "entity type",
)
_LABEL_UBI = (
    "numri i biznesit",
    "numri unik",
    "ubi",
    "nrb",
    "numri i regjistrimit",
    "broj biznisa",
    "business number",
    "registration number",
)
_LABEL_NF = (
    "numri fiskal",
    "nf",
    "fiskalni broj",
    "tax id",
    "tax number",
    "vat",
)
_LABEL_DIRECTOR = (
    "pronari",
    "pronar",
    "perfaqesues",
    "përfaqësues",
    "administrator",
    "administratori",
    "drejtori",
    "drejtuesi",
    "direktor",
    "owner",
    "director",
    "manager",
    "representative",
)
_LABEL_CAPITAL = (
    "kapitali",
    "kapitali themeltar",
    "kapital",
    "share capital",
    "founding capital",
)
_LABEL_OBJECT = (
    "veprimtaria",
    "veprimtaria kryesore",
    "fusha e veprimtarise",
    "fusha e veprimtarisë",
    "delatnost",
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
    "aktivan",
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


def _normalize_ubi(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if not _UBI_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kosovo business number must be 8 digits + letter (e.g. 70123456A), got: {value}"
        )
    return cleaned


def _normalize_nf(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    # Kosovo VAT under the EU prefix convention is rendered "XK" + NF.
    # Strip the prefix only when followed by a valid NF body to avoid
    # truncating real input.
    if cleaned.startswith("XK") and _NF_RE.match(cleaned[2:]):
        cleaned = cleaned[2:]
    if not _NF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kosovo fiscal number must be 9 digits, got: {value}"
        )
    return cleaned


def _parse_xk_date(value: str | None) -> date | None:
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
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    else:
        tail = cleaned.rsplit(".", 1)[-1] if "." in cleaned else ""
        if tail and len(tail) == 3:
            cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


class XKAdapter(CountryAdapter):
    country_code = "XK"
    country_name = "Kosovo"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://arbk.rks-gov.net"
    SEARCH_PATH = "/page.aspx?id=2,32"
    LOOKUP_PATH = "/page.aspx?id=2,32"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "sq;q=0.9,sr;q=0.8,en;q=0.7",
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
        portal_alive = (
            "arbk" in low or "biznes" in low or "register" in low or "regjistr" in low
        )
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
                    "arbk.rks-gov.net responded but markup unrecognised; "
                    "site may be under maintenance."
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
                "Lookup live via arbk.rks-gov.net HTML scrape. Financial "
                "statements are not centrally published in machine-readable "
                "form."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.SEARCH_PATH,
                params={"emri": query, "name": query, "q": query},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            page_text = _decode_response(resp)

        rows = _extract_search_rows(page_text)
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            ubi = row.get("ubi")
            if not row.get("name"):
                continue
            ids: list[RegistryIdentifier] = []
            if ubi:
                ids.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=ubi,
                        label="Numri Unik i Biznesit",
                    )
                )
            nf = row.get("nf")
            if nf:
                ids.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=nf,
                        label="Numri Fiskal",
                    )
                )
            row_id = ubi or nf
            if not row_id:
                continue
            matches.append(
                CompanyMatch(
                    id=row_id,
                    name=row["name"],
                    country=self.country_code,
                    identifiers=ids,
                    address=row.get("address"),
                    status=_classify_status(row.get("status_raw")),
                    source_url=f"{self.BASE_URL}{self.SEARCH_PATH}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            ident = _normalize_ubi(value)
            param_keys = ("ubi", "nrb", "search", "q")
        elif id_type == IdentifierType.VAT:
            ident = _normalize_nf(value)
            param_keys = ("nf", "fiskal", "search", "q")
        else:
            raise InvalidIdentifierError(
                "Kosovo adapter only supports COMPANY_NUMBER (UBI) or VAT (NF), "
                f"got {id_type}"
            )

        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.LOOKUP_PATH,
                params={k: ident for k in param_keys},
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
                    "nije pronađen",
                    "nije pronaden",
                )
            ):
                return None
            return None

        identifiers: list[RegistryIdentifier] = []
        ubi_val = record.get("ubi") if id_type == IdentifierType.VAT else ident
        nf_val = record.get("nf") if id_type == IdentifierType.COMPANY_NUMBER else ident
        if ubi_val and _UBI_RE.match(ubi_val):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=ubi_val,
                    label="Numri Unik i Biznesit",
                )
            )
        if nf_val and _NF_RE.match(nf_val):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=nf_val,
                    label="Numri Fiskal",
                )
            )

        director_name = (record.get("director") or "").strip()

        return CompanyDetails(
            id=ubi_val or ident,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_xk_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=_parse_capital_amount(record.get("capital")),
            capital_currency="EUR",
            identifiers=identifiers,
            raw={
                "source": "arbk.rks-gov.net",
                "fields": record,
                "director_name": director_name or None,
                "business_object": record.get("business_object"),
            },
            source_url=f"{self.BASE_URL}{self.LOOKUP_PATH}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        return []


def _decode_response(resp: httpx.Response) -> str:
    """Decode the body, preferring UTF-8 (arbk.rks-gov.net uses UTF-8).

    Falls back defensively to cp1250/Latin-1 derivatives when an upstream
    proxy strips encoding headers so Albanian (ë, ç) and Serbian (š, đ)
    diacritics survive.
    """
    body = resp.content
    if not body:
        return ""
    for encoding in ("utf-8", "cp1250", "cp1252", "iso-8859-1"):
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
    """Pull the company fields out of an ARBK detail page."""
    if not html:
        return {}

    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("XK ARBK HTML parse failed: %s", exc)
        return {}

    cells = [c for c in parser.cells if c]
    record: dict[str, Any] = {}
    for label_cell, value_cell in zip(cells, cells[1:]):
        if not value_cell:
            continue
        if "name" not in record and _match_label(label_cell, _LABEL_NAME):
            record["name"] = value_cell
        elif "status_raw" not in record and _match_label(label_cell, _LABEL_STATUS):
            record["status_raw"] = value_cell
        elif "address" not in record and _match_label(label_cell, _LABEL_ADDRESS):
            record["address"] = value_cell
        elif "registration_date" not in record and _match_label(
            label_cell, _LABEL_REG_DATE
        ):
            record["registration_date"] = value_cell
        elif "legal_form" not in record and _match_label(label_cell, _LABEL_LEGAL_FORM):
            record["legal_form"] = value_cell
        elif "ubi" not in record and _match_label(label_cell, _LABEL_UBI):
            up = value_cell.upper().replace(" ", "")
            if _UBI_RE.match(up):
                record["ubi"] = up
        elif "nf" not in record and _match_label(label_cell, _LABEL_NF):
            up = value_cell.upper().replace(" ", "")
            if up.startswith("XK") and _NF_RE.match(up[2:]):
                up = up[2:]
            if _NF_RE.match(up):
                record["nf"] = up
        elif "director" not in record and _match_label(label_cell, _LABEL_DIRECTOR):
            record["director"] = value_cell
        elif "capital" not in record and _match_label(label_cell, _LABEL_CAPITAL):
            record["capital"] = value_cell
        elif "business_object" not in record and _match_label(label_cell, _LABEL_OBJECT):
            record["business_object"] = value_cell

    if "name" not in record:
        # ARBK sometimes renders the company name above the table in a
        # heading element when only one match is returned.
        m = re.search(
            r"<h[12][^>]*>\s*([^<]{3,200})\s*</h[12]>",
            html,
            re.IGNORECASE,
        )
        if m:
            candidate = unescape(re.sub(r"\s+", " ", m.group(1)).strip())
            low = candidate.lower()
            if "arbk" not in low and "kerko" not in low and "kërko" not in low:
                record["name"] = candidate
    return record


def _extract_search_rows(html: str) -> list[dict[str, Any]]:
    """Best-effort parse of the ARBK name-search results page.

    Rows expose the company name alongside the UBI (8 digits + letter).
    The UBI shape is unique, so it serves as the row anchor.
    """
    if not html:
        return []
    parser = _SearchRowParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("XK ARBK search parse failed: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        cleaned = [c for c in cells if c]
        if len(cleaned) < 2:
            continue
        ubi_match: str | None = None
        nf_match: str | None = None
        for c in cleaned:
            up = c.upper().replace(" ", "")
            if not ubi_match and _UBI_RE.match(up):
                ubi_match = up
            elif not nf_match and _NF_RE.match(up):
                nf_match = up
        if not (ubi_match or nf_match):
            continue
        name_candidate: str | None = None
        for c in cleaned:
            up = c.upper().replace(" ", "")
            if up == ubi_match or up == nf_match:
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
            "naziv",
        }:
            continue
        rows.append(
            {
                "name": name_candidate,
                "ubi": ubi_match,
                "nf": nf_match,
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
                "prishtine",
                "prishtinë",
                "prishtina",
                "pristina",
                "peje",
                "pejë",
                "prizren",
                "mitrovice",
                "mitrovicë",
                "ferizaj",
                "gjilan",
                "gjakove",
                "gjakovë",
                "rruga",
                "rr.",
                "street",
                "ulica",
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
