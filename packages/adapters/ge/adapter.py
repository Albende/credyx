"""Georgia adapter — NAPR (National Agency of Public Registry) public portal.

Source coverage:

* https://enreg.reestri.gov.ge/main.php — the bilingual (ქართული /
  English) public business register operated by NAPR. The site renders
  a search form whose results page lists matching legal persons; each
  result links to a per-company detail page keyed by the 9-digit
  Identification Number (`s_legal_person_idnumber`). The page returns
  the registered name (Georgian + Latin transliteration where filed),
  legal form, status, registered address, declared capital, and
  directors / managers. No authentication, no JSON contract — pure
  HTML scrape.

  Name search is JS-rendered: a plain GET to the result endpoint
  returns the page shell with an empty `<div id="search_result">` and
  populates it via XHR fired from the bundled jQuery. We drive the
  search through the shared `BrowserPool` (Playwright/Chromium) so the
  XHR runs and we can read the post-render DOM. Direct-ID lookup is
  still done with plain httpx because that endpoint server-renders.
* https://rs.ge/ — Revenue Service VAT validator. Public but partial
  (no per-company details exposed; not used here).
* https://gse.ge/ — Georgian Stock Exchange. Limited free coverage of
  listed-issuer disclosures; out of scope for the free MVP.

Identifier:
- VAT / COMPANY_NUMBER → "Identification Number" (საიდენტიფიკაციო
  ნომერი), always 9 digits. The same number serves as the corporate
  tax ID, the VAT registration ID, and the commercial registry primary
  key. NAPR does not issue a separate company number.
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
from packages.adapters._base.browser import get_browser_pool
from packages.adapters._base.errors import (
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    Director,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^\d{9}$")

# Bank of Georgia — a well-known active legal person used as a liveness probe.
_HEALTH_PROBE_ID = "204378869"

# Field labels NAPR may render in Georgian, Latin transliteration, or English.
# Matching is case-insensitive and stripped of trailing colons.
_LABEL_NAME = (
    "დასახელება",
    "სუბიექტის დასახელება",
    "სახელწოდება",
    "name",
    "company name",
    "legal person",
)
_LABEL_LEGAL_FORM = (
    "სამართლებრივი ფორმა",
    "ორგანიზაციულ-სამართლებრივი ფორმა",
    "legal form",
    "form",
)
_LABEL_STATUS = (
    "სტატუსი",
    "მდგომარეობა",
    "status",
    "state",
)
_LABEL_ADDRESS = (
    "მისამართი",
    "იურიდიული მისამართი",
    "address",
    "legal address",
)
_LABEL_CAPITAL = (
    "კაპიტალი",
    "საწესდებო კაპიტალი",
    "capital",
    "share capital",
)
_LABEL_REG_DATE = (
    "რეგისტრაციის თარიღი",
    "დაფუძნების თარიღი",
    "registration date",
    "incorporation date",
)
_LABEL_ID = (
    "საიდენტიფიკაციო ნომერი",
    "ს/ნ",
    "identification number",
    "id number",
)
_LABEL_DIRECTOR = (
    "ხელმძღვანელი",
    "დირექტორი",
    "მენეჯერი",
    "მმართველი",
    "director",
    "manager",
    "head",
)

_STATUS_ACTIVE_TOKENS = (
    "მოქმედი",  # "acting"
    "აქტიური",  # "active"
    "active",
    "registered",
)
_STATUS_INACTIVE_TOKENS = (
    "გაუქმებული",  # "cancelled"
    "ლიკვიდირებული",  # "liquidated"
    "შეჩერებული",  # "suspended"
    "გადახდისუუნარო",  # "insolvent"
    "liquidated",
    "cancelled",
    "suspended",
    "inactive",
    "dissolved",
)


def _normalize_id(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("GE"):
        cleaned = cleaned[2:]
    if not _ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Georgia Identification Number must be exactly 9 digits, got: {value}"
        )
    return cleaned


def _parse_ge_date(value: str | None) -> date | None:
    """NAPR renders dates as DD.MM.YYYY or DD/MM/YYYY; tolerate ISO too."""
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
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
    if any(token in raw for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _parse_capital(raw: str | None) -> tuple[float | None, str | None]:
    """Pull an amount + currency out of a free-form capital string.

    NAPR records capital like "100 000,00 GEL" or "5000 ლარი" — we keep
    the parser permissive about thousand separators and decimal commas.
    """
    if not raw:
        return None, None
    currency: str | None = None
    if re.search(r"\b(GEL|gel|₾|ლარ)", raw):
        currency = "GEL"
    elif re.search(r"\bUSD\b", raw, re.IGNORECASE):
        currency = "USD"
    elif re.search(r"\bEUR\b", raw, re.IGNORECASE):
        currency = "EUR"

    digits = re.sub(r"[^\d,.\s]", "", raw).strip()
    if not digits:
        return None, currency
    # Treat the last separator as decimal; flatten thousands.
    last_comma = digits.rfind(",")
    last_dot = digits.rfind(".")
    if last_comma > last_dot:
        normalized = digits.replace(".", "").replace(" ", "").replace(",", ".")
    else:
        normalized = digits.replace(",", "").replace(" ", "")
    try:
        return float(normalized), currency
    except ValueError:
        return None, currency


class GEAdapter(CountryAdapter):
    country_code = "GE"
    country_name = "Georgia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://enreg.reestri.gov.ge"
    SEARCH_PATH = "/main.php"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ka,en;q=0.7,ru;q=0.5",
            },
            timeout=25.0,
        )

    async def _render_search_page(self, query: str) -> str:
        """Drive NAPR's JS-rendered search form via the shared browser pool.

        enreg.reestri.gov.ge fires an XHR on submit and re-paints the
        `#search_result` block; a plain httpx GET only sees the empty
        shell. We navigate, fill the legal-person name field, submit,
        and wait for the result container to populate.
        """
        url = (
            f"{self.BASE_URL}{self.SEARCH_PATH}"
            "?c=app&m=show_legal_person_form"
        )
        pool = get_browser_pool()
        async with pool.acquire(locale="ka-GE") as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Fill whichever input the registry exposes for the legal
                # person name. The portal has shipped slightly different
                # field names across revisions; try the common ones in
                # order and stop at the first that exists.
                filled = False
                for selector in (
                    "input[name='s_legal_person_name']",
                    "input#s_legal_person_name",
                    "input[name='legal_person_name']",
                ):
                    if await page.locator(selector).count():
                        await page.fill(selector, query)
                        filled = True
                        break
                if not filled:
                    raise BlockedByRegistryError(
                        "enreg.reestri.gov.ge search form not found — page "
                        "markup may have changed."
                    )
                # Submit. NAPR's form is keyed on its own submit button;
                # falling back to Enter covers minor UI variants.
                submit = page.locator("input[type=submit], button[type=submit]")
                if await submit.count():
                    await submit.first.click()
                else:
                    await page.keyboard.press("Enter")
                # Wait for either the result table or an explicit "no
                # results" indicator.
                try:
                    await page.wait_for_selector(
                        "table tr a[href*='show_legal_person'], #search_result",
                        timeout=20_000,
                    )
                except Exception:
                    # Falling back to whatever the DOM is now — extraction
                    # tolerates an empty page.
                    pass
                return await page.content()
            finally:
                await page.close()

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    self.SEARCH_PATH,
                    params={
                        "c": "app",
                        "m": "show_legal_person",
                        "legal_code": _HEALTH_PROBE_ID,
                    },
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
                    "enreg.reestri.gov.ge responded but probe ID returned no "
                    "structured fields; page markup may have changed."
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
                "Name search + ID lookup via NAPR HTML. No centralized free "
                "financial dataset."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        query = (name or "").strip()
        if not query:
            return []

        page_text = await self._render_search_page(query)
        results = _extract_search_results(page_text)
        out: list[CompanyMatch] = []
        for item in results[:limit]:
            legal_code = item.get("id")
            if not legal_code:
                continue
            out.append(
                CompanyMatch(
                    id=legal_code,
                    name=item.get("name", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT,
                            value=legal_code,
                            label="Identification Number",
                        ),
                    ],
                    address=item.get("address"),
                    status=_classify_status(item.get("status_raw")),
                    source_url=(
                        f"{self.BASE_URL}{self.SEARCH_PATH}?c=app&"
                        f"m=show_legal_person&legal_code={legal_code}"
                    ),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                "Georgia adapter accepts only VAT or COMPANY_NUMBER "
                f"(9-digit Identification Number), got {id_type}"
            )
        legal_code = _normalize_id(value)
        params = {
            "c": "app",
            "m": "show_legal_person",
            "legal_code": legal_code,
        }
        async with self._client() as client:
            resp = await get_with_retry(client, self.SEARCH_PATH, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            page_text = _decode_response(resp)

        record = _extract_company_record(page_text)
        if not record.get("name"):
            low = page_text.lower()
            if any(token in low for token in ("not found", "ვერ მოიძებნა", "არ არსებობს")):
                return None
            return None

        capital_amount, capital_currency = _parse_capital(record.get("capital"))
        directors = [
            Director(name=d) for d in record.get("directors", []) if d
        ]

        source_url = (
            f"{self.BASE_URL}{self.SEARCH_PATH}?c=app&"
            f"m=show_legal_person&legal_code={legal_code}"
        )

        return CompanyDetails(
            id=legal_code,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_ge_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=capital_amount,
            capital_currency=capital_currency or "GEL",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=legal_code,
                    label="Identification Number",
                ),
            ],
            directors=directors,
            raw={
                "source": "enreg.reestri.gov.ge/show_legal_person",
                "fields": record,
            },
            source_url=source_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # NAPR does not publish balance sheets; the Service for Accounting,
        # Reporting and Auditing Supervision (saras.gov.ge) operates a
        # reporting portal whose public search is captcha-gated and whose
        # documents are PDFs. Out of scope for the free MVP — surface the
        # absence honestly rather than fabricate filings.
        return []


def _decode_response(resp: httpx.Response) -> str:
    """Decode the response body as text, preferring UTF-8 then cp1251.

    enreg.reestri.gov.ge declares UTF-8 in modern responses but a few
    legacy endpoints have surfaced as cp1251; we try both before falling
    back to httpx's guess.
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


class _CellParser(HTMLParser):
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


def _match_label(cell: str, candidates: tuple[str, ...]) -> bool:
    low = cell.strip().rstrip(":").strip().lower()
    return any(label.lower() in low for label in candidates)


def _extract_company_record(html: str) -> dict[str, Any]:
    """Pull the legal-person fields out of the show_legal_person page."""
    if not html:
        return {}

    parser = _CellParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("GE enreg HTML parse failed: %s", exc)
        return {}

    cells = [c for c in parser.cells if c]
    record: dict[str, Any] = {}
    directors: list[str] = []
    for label_cell, value_cell in zip(cells, cells[1:]):
        if not value_cell or value_cell == label_cell:
            continue
        if "name" not in record and _match_label(label_cell, _LABEL_NAME):
            record["name"] = value_cell
        elif "legal_form" not in record and _match_label(label_cell, _LABEL_LEGAL_FORM):
            record["legal_form"] = value_cell
        elif "status_raw" not in record and _match_label(label_cell, _LABEL_STATUS):
            record["status_raw"] = value_cell
        elif "address" not in record and _match_label(label_cell, _LABEL_ADDRESS):
            record["address"] = value_cell
        elif "capital" not in record and _match_label(label_cell, _LABEL_CAPITAL):
            record["capital"] = value_cell
        elif "registration_date" not in record and _match_label(label_cell, _LABEL_REG_DATE):
            record["registration_date"] = value_cell
        elif _match_label(label_cell, _LABEL_DIRECTOR):
            if value_cell not in directors:
                directors.append(value_cell)

    if directors:
        record["directors"] = directors
    return record


_RESULT_LINK_RE = re.compile(
    r"legal_code=(\d{9})[^>]*>\s*([^<]+?)\s*<", re.IGNORECASE
)


def _extract_search_results(html: str) -> list[dict[str, Any]]:
    """Pull (id, name) tuples out of the result-list HTML.

    The NAPR result page renders each match as a row whose first cell is
    an anchor pointing back to `show_legal_person&legal_code=<id>`. We
    extract those plus the surrounding row text for status/address. The
    parser is forgiving: if the layout changes, callers fall back to
    looking up known IDs directly.
    """
    if not html:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _RESULT_LINK_RE.finditer(html):
        legal_code = match.group(1)
        if legal_code in seen:
            continue
        seen.add(legal_code)
        name = unescape(match.group(2)).strip()
        out.append({"id": legal_code, "name": name})

    if out:
        return out

    # Fallback: walk the table cells and pair 9-digit IDs with the
    # adjacent name cell. Useful when the registry renders IDs as plain
    # text instead of anchors.
    parser = _CellParser()
    try:
        parser.feed(html)
    except Exception:
        return out
    cells = [c for c in parser.cells if c]
    for idx, cell in enumerate(cells):
        if _ID_RE.match(cell.replace(" ", "")) and cell not in seen:
            legal_code = cell.replace(" ", "")
            name = cells[idx - 1] if idx > 0 else ""
            seen.add(legal_code)
            out.append({"id": legal_code, "name": name})
    return out
