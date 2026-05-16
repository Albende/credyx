"""Azerbaijan adapter — e-taxes.gov.az public VÖEN lookup.

Source coverage:

* https://www.e-taxes.gov.az/ebyn/commersialChek.jsp?vergi_id={voen} —
  the public "commercial taxpayer check" page operated by the State Tax
  Service (DSX). Returns an HTML fragment with the taxpayer name,
  status (active/closed), registered address and registration date.
  No authentication, no JSON contract — pure HTML scrape.
* State Statistics Committee (stat.gov.az) and Ministry of Justice
  (justice.gov.az) provide bulletins / NGO registers, but the
  commercial register has no public search endpoint and financial
  statements are not published online for non-listed companies.

Identifier:
- VAT → VÖEN (Vergi Ödəyicisinin Eyniləşdirmə Nömrəsi). Always 10 digits.
  Some sources prefix with "AZ"; we strip it. Same number serves as the
  VAT registration ID and the corporate tax ID.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

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

_VOEN_RE = re.compile(r"^\d{10}$")

# A well-known active taxpayer used as a liveness probe — SOCAR.
_HEALTH_PROBE_VOEN = "9900003871"

# Field labels the public page may render in Azerbaijani Latin script.
# Russian/Cyrillic labels are also possible; we keep matchers loose.
_LABEL_NAME = (
    "vergi ödəyicisinin adı",
    "vergi odeyicisinin adi",
    "ad",
    "наименование",
    "название",
    "name",
)
_LABEL_STATUS = (
    "vəziyyət",
    "veziyyet",
    "status",
    "статус",
    "состояние",
)
_LABEL_ADDRESS = (
    "ünvan",
    "unvan",
    "ünvanı",
    "адрес",
    "address",
    "юридический адрес",
)
_LABEL_REG_DATE = (
    "qeydiyyat tarixi",
    "qeydiyyata alınma tarixi",
    "дата регистрации",
    "registration date",
)
_LABEL_LEGAL_FORM = (
    "təşkilati-hüquqi forma",
    "teshkilati huquqi forma",
    "организационно-правовая форма",
    "legal form",
)

_STATUS_ACTIVE_TOKENS = ("fəal", "aktiv", "fealdir", "действующ", "active")
_STATUS_INACTIVE_TOKENS = (
    "ləğv",
    "bağlan",
    "qeyri-fəal",
    "ликвидир",
    "закрыт",
    "недейств",
    "inactive",
    "closed",
)


def _normalize_voen(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("AZ"):
        cleaned = cleaned[2:]
    if not _VOEN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Azerbaijan VÖEN must be exactly 10 digits, got: {value}"
        )
    return cleaned


def _parse_az_date(value: str | None) -> date | None:
    """e-taxes renders dates as DD.MM.YYYY; tolerate ISO and slashes too."""
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


class AZAdapter(CountryAdapter):
    country_code = "AZ"
    country_name = "Azerbaijan"
    identifier_types = [IdentifierType.VAT]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://www.e-taxes.gov.az"
    LOOKUP_PATH = "/ebyn/commersialChek.jsp"

    def _client(self):
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "az,en;q=0.7,ru;q=0.5",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    self.LOOKUP_PATH,
                    params={"vergi_id": _HEALTH_PROBE_VOEN},
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
        record = _extract_taxpayer_record(page_text)
        if not record.get("name"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="e-taxes responded but probe VÖEN returned no name; "
                "page markup may have changed.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={
                "search": False,
                "lookup": True,
                "financials": False,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Lookup only — e-taxes does not expose name search or "
            "filed financial statements publicly.",
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "AZ e-taxes does not expose name search publicly; "
            "look up by VÖEN (10-digit tax ID) instead."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.VAT:
            raise InvalidIdentifierError(
                f"Azerbaijan adapter only supports VAT (VÖEN), got {id_type}"
            )
        voen = _normalize_voen(value)
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.LOOKUP_PATH,
                params={"vergi_id": voen},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            page_text = _decode_response(resp)

        record = _extract_taxpayer_record(page_text)
        if not record.get("name"):
            # Page rendered but no taxpayer found — distinguish "unknown VÖEN"
            # from a markup change. e-taxes shows a localized "no record" line.
            low = page_text.lower()
            if any(
                token in low
                for token in ("tapılmadı", "tapilmadi", "не найден", "not found")
            ):
                return None
            return None

        source_url = (
            f"{self.BASE_URL}{self.LOOKUP_PATH}?vergi_id={voen}"
        )

        return CompanyDetails(
            id=voen,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_az_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=None,
            capital_currency="AZN",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=voen,
                    label="VÖEN",
                ),
            ],
            raw={
                "source": "e-taxes.gov.az/commersialChek",
                "fields": record,
            },
            source_url=source_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raise AdapterNotImplementedError(
            "Azerbaijan financial statements are not published publicly. "
            "Listed-issuer reports live on the Baku Stock Exchange (BSE) "
            "site only as PDFs and are out of scope for the free MVP."
        )


def _decode_response(resp) -> str:
    """Decode the response body as text, defaulting to UTF-8.

    e-taxes.gov.az has historically served pages as windows-1251 / cp1251
    without a charset header; httpx then falls back to latin-1, which
    mangles Azerbaijani diacritics and Cyrillic. We try UTF-8 first, then
    cp1251, before letting httpx guess.
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
    """Flatten every <td>/<th> cell into a list of stripped text strings.

    The e-taxes page renders the taxpayer record as a two-column table:
    label on the left, value on the right. We sweep all cells and then
    walk pairwise.
    """

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
    low = cell.lower().strip().rstrip(":").strip()
    return any(label in low for label in candidates)


def _extract_taxpayer_record(html: str) -> dict[str, Any]:
    """Pull the taxpayer fields out of the commersialChek.jsp HTML."""
    if not html:
        return {}

    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("AZ e-taxes HTML parse failed: %s", exc)
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

    if "name" not in record:
        # Fallback: scan flattened text for a heading-style "Adı: …" pattern.
        flat = re.sub(r"<[^>]+>", " ", html)
        flat = unescape(re.sub(r"\s+", " ", flat)).strip()
        m = re.search(
            r"(?:vergi\s+ödəyicisinin\s+adı|ad[ıi])\s*[:\-]\s*([^\n\r<]+?)\s{2,}",
            flat,
            re.IGNORECASE,
        )
        if m:
            record["name"] = m.group(1).strip()
    return record
