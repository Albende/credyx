"""Armenia adapter — e-Register.am State Register of Legal Entities.

Source coverage:

* https://www.e-register.am/ — the State Register of Legal Entities of
  the Republic of Armenia (operated by the Ministry of Justice). It
  publishes a free per-company HTML view keyed by either the
  state-registry serial number or the taxpayer identification number
  (TIN, locally ՀՎՀՀ — 8 digits). Available in Armenian, Russian, and
  English; the English/Russian endpoints expose the same record under
  ``/company/{lang}/{id}``-style paths. No authentication.
* https://src.am/ — State Revenue Committee VAT/TIN validator. Useful as
  a sanity probe; does not return structured registry data we can rely
  on without scraping a session-bound page.
* https://amx.am/ — Armenia Securities Exchange (NASDAQ OMX Armenia /
  AMX). Lists ~10 traded equities; filings are PDF-only and out of
  scope for the free MVP.

Identifier:
- VAT → TIN / ՀՎՀՀ (Hark Vcharoghi Hashvarkayin Hamar). 8 digits. Some
  sources prefix with ``AM``; we strip it. Same number serves as VAT
  registration ID and corporate tax ID.
- COMPANY_NUMBER → state-registry serial. Variable length, often
  hyphenated (e.g. ``290.110.05049``). We pass it through with
  whitespace stripped.

No centralized free source of filed financial statements exists for
Armenian companies; ``fetch_financials`` therefore returns an empty
list rather than fabricating data. (Listed-issuer reports on AMX are
PDF-only and would need a separate pipeline.)
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

# Ardshinbank CJSC — a stable, well-known liveness probe.
_HEALTH_PROBE_TIN = "02525118"

# e-Register renders the company card as a label/value table. Labels appear
# in Armenian (Unicode), Russian (Cyrillic), and English depending on the
# current site language. Match loosely on all three.
_LABEL_NAME = (
    "անվանումը",
    "ընկերության անվանումը",
    "ֆիրմային անվանումը",
    "name",
    "company name",
    "наименование",
    "название",
    "полное наименование",
)
_LABEL_STATUS = (
    "կարգավիճակ",
    "վիճակ",
    "status",
    "статус",
    "состояние",
)
_LABEL_ADDRESS = (
    "հասցե",
    "գտնվելու վայր",
    "իրավաբանական հասցե",
    "address",
    "registered address",
    "адрес",
    "юридический адрес",
)
_LABEL_REG_DATE = (
    "գրանցման ամսաթիվ",
    "գրանցման օր",
    "registration date",
    "date of registration",
    "дата регистрации",
)
_LABEL_LEGAL_FORM = (
    "կազմակերպական-իրավական ձև",
    "կազմակերպաիրավական ձև",
    "legal form",
    "type",
    "организационно-правовая форма",
)
_LABEL_TIN = (
    "հվհհ",
    "հարկ վճարողի հաշվառման համար",
    "tin",
    "tax id",
    "taxpayer id",
    "инн",
    "учетный номер налогоплательщика",
)
_LABEL_REG_NUMBER = (
    "գրանցման համար",
    "պետական գրանցման համար",
    "registration number",
    "state registration number",
    "регистрационный номер",
    "номер регистрации",
)
_LABEL_DIRECTOR = (
    "տնօրեն",
    "գործադիր մարմին",
    "ղեկավար",
    "executive",
    "director",
    "руководитель",
    "директор",
)
_LABEL_CAPITAL = (
    "կանոնադրական կապիտալ",
    "հիմնադիր կապիտալ",
    "charter capital",
    "share capital",
    "уставный капитал",
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
    "ոչ ակտիվ",
    "inactive",
    "liquidated",
    "dissolved",
    "closed",
    "ликвидир",
    "прекращ",
    "закрыт",
    "недейств",
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
    """e-Register renders dates as DD.MM.YYYY; tolerate ISO and slashes."""
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


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(token in low for token in _STATUS_INACTIVE_TOKENS):
        return "inactive"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


class AMAdapter(CountryAdapter):
    country_code = "AM"
    country_name = "Armenia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://www.e-register.am"

    # The public site supports per-language paths. We default to English so
    # responses use Latin script wherever the registry has it.
    SEARCH_PATH = "/en/search"
    LOOKUP_PATH = "/en/company"

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
                resp = await get_with_retry(
                    client,
                    self.LOOKUP_PATH,
                    params={"tin": _HEALTH_PROBE_TIN},
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
                notes=str(exc)[:200],
            )
        record = _extract_company_record(page_text)
        if not record.get("name"):
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
                    "e-Register responded but probe TIN returned no name; "
                    "page markup may have changed."
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
                "Lookup live via e-register.am HTML scrape. Financial "
                "statements are not centrally published."
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
                self.SEARCH_PATH,
                params={"q": query},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            page_text = _decode_response(resp)

        rows = _extract_search_rows(page_text)
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            identifier = row.get("tin") or row.get("reg_number")
            if not identifier or not row.get("name"):
                continue
            ids: list[RegistryIdentifier] = []
            if row.get("tin"):
                ids.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=row["tin"],
                        label="ՀՎՀՀ / TIN",
                    )
                )
            if row.get("reg_number"):
                ids.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=row["reg_number"],
                        label="State Registry Number",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=identifier,
                    name=row["name"],
                    country=self.country_code,
                    identifiers=ids,
                    address=row.get("address"),
                    status=_classify_status(row.get("status_raw")),
                    source_url=(
                        f"{self.BASE_URL}{self.LOOKUP_PATH}"
                        f"?tin={row['tin']}"
                        if row.get("tin")
                        else f"{self.BASE_URL}{self.SEARCH_PATH}?q={query}"
                    ),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            tin = _normalize_tin(value)
            params = {"tin": tin}
            local_id = tin
        elif id_type == IdentifierType.COMPANY_NUMBER:
            reg = _normalize_reg_number(value)
            params = {"reg_number": reg}
            local_id = reg
        else:
            raise InvalidIdentifierError(
                "Armenia adapter only supports VAT (TIN) or COMPANY_NUMBER "
                f"(state-registry number), got {id_type}"
            )

        async with self._client() as client:
            resp = await get_with_retry(client, self.LOOKUP_PATH, params=params)
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
                    "չի գտնվել",
                    "not found",
                    "no results",
                    "не найден",
                )
            ):
                return None
            return None

        tin = record.get("tin") or (
            local_id if id_type == IdentifierType.VAT else None
        )
        reg_number = record.get("reg_number") or (
            local_id if id_type == IdentifierType.COMPANY_NUMBER else None
        )

        identifiers: list[RegistryIdentifier] = []
        if tin:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=tin,
                    label="ՀՎՀՀ / TIN",
                )
            )
        if reg_number:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=reg_number,
                    label="State Registry Number",
                )
            )

        source_url = (
            f"{self.BASE_URL}{self.LOOKUP_PATH}?tin={tin}"
            if tin
            else f"{self.BASE_URL}{self.LOOKUP_PATH}?reg_number={reg_number}"
        )

        return CompanyDetails(
            id=tin or reg_number or local_id,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_am_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=_parse_capital_amount(record.get("capital")),
            capital_currency="AMD",
            identifiers=identifiers,
            raw={
                "source": "e-register.am",
                "fields": record,
            },
            source_url=source_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raise AdapterNotImplementedError(
            "Armenian financial statements are not centrally published. "
            "Annual accounts are filed with the State Revenue Committee but "
            "not exposed via a free portal. Listed-issuer reports on AMX "
            "(amx.am) are PDF-only and out of scope for the free MVP."
        )


def _decode_response(resp: httpx.Response) -> str:
    """Decode the body, preferring UTF-8 then Windows-1251 fallbacks.

    e-register.am serves UTF-8 today, but legacy mirrors and the SRC
    pages occasionally use windows-1251 for Russian text; we keep the
    same fallback chain as the AZ adapter to stay robust.
    """
    body = resp.content
    if not body:
        return ""
    for encoding in ("utf-8", "cp1251", "windows-1251"):
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
        self._href: str | None = None
        self.row_hrefs: list[str | None] = []
        self._row_href: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            self._in_row = True
            self._row = []
            self._row_href = None
        elif tag in ("td", "th") and self._in_row:
            self._in_cell += 1
            self._buf = []
        elif tag == "a" and self._in_cell:
            for k, v in attrs:
                if k == "href" and v and self._row_href is None:
                    self._row_href = v
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
                self.row_hrefs.append(self._row_href)
            self._in_row = False
            self._row = []
            self._row_href = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf.append(data)


def _match_label(cell: str, candidates: tuple[str, ...]) -> bool:
    low = cell.lower().strip().rstrip(":").strip()
    return any(label in low for label in candidates)


def _extract_company_record(html: str) -> dict[str, Any]:
    """Pull the company fields out of an e-register.am detail page."""
    if not html:
        return {}

    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("AM e-register HTML parse failed: %s", exc)
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
        elif "tin" not in record and _match_label(label_cell, _LABEL_TIN):
            digits = re.sub(r"\D", "", value_cell)
            if _TIN_RE.match(digits):
                record["tin"] = digits
        elif "reg_number" not in record and _match_label(
            label_cell, _LABEL_REG_NUMBER
        ):
            record["reg_number"] = value_cell
        elif "director" not in record and _match_label(
            label_cell, _LABEL_DIRECTOR
        ):
            record["director"] = value_cell
        elif "capital" not in record and _match_label(
            label_cell, _LABEL_CAPITAL
        ):
            record["capital"] = value_cell

    if "name" not in record:
        # Fallback: try a heading-style match. e-register sometimes renders
        # the company name above the table inside an <h1>/<h2>.
        m = re.search(
            r"<h[12][^>]*>\s*([^<]{3,200})\s*</h[12]>",
            html,
            re.IGNORECASE,
        )
        if m:
            candidate = unescape(re.sub(r"\s+", " ", m.group(1)).strip())
            # Avoid grabbing the site title.
            if "e-register" not in candidate.lower():
                record["name"] = candidate
    return record


def _extract_search_rows(html: str) -> list[dict[str, Any]]:
    """Best-effort parse of the e-register name-search results page.

    The result table layout varies by site language; we pick out the TIN
    (8 consecutive digits) and the longest non-numeric cell as the name.
    """
    if not html:
        return []
    parser = _SearchRowParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("AM e-register search parse failed: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        cleaned = [c for c in cells if c]
        if len(cleaned) < 2:
            continue
        tin_match: str | None = None
        for c in cleaned:
            digits = re.sub(r"\D", "", c)
            if _TIN_RE.match(digits):
                tin_match = digits
                break
        # Skip header rows that have no TIN and look like label text.
        name_candidate: str | None = None
        for c in cleaned:
            if c == tin_match:
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
            "company",
            "company name",
            "անվանումը",
            "наименование",
        }:
            continue
        rows.append(
            {
                "name": name_candidate,
                "tin": tin_match,
                "reg_number": _pick_reg_number(cleaned, exclude=tin_match),
                "address": _pick_address(cleaned),
                "status_raw": _pick_status(cleaned),
            }
        )
    return rows


def _pick_reg_number(cells: list[str], *, exclude: str | None) -> str | None:
    for c in cells:
        if c == exclude:
            continue
        if re.fullmatch(r"\d{2,4}[./\-]\d{2,4}[./\-]\d{2,7}", c):
            return c
    return None


def _pick_address(cells: list[str]) -> str | None:
    for c in cells:
        low = c.lower()
        if any(
            token in low
            for token in ("yerevan", "երևան", "ереван", "str.", "ave", "փող", "ул.")
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


def _parse_capital_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.,]", "", raw).replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
