"""Kyrgyzstan adapter — Ministry of Justice legal-entity register.

Source coverage:

* https://register.minjust.gov.kg/register/ — the Ministry of Justice
  (Министерство юстиции Кыргызской Республики) public register of legal
  entities, branches, and representative offices. The portal exposes a
  Russian-language search form whose results list links to per-entity
  detail pages keyed by the 14-digit INN (ИНН, идентификационный
  налоговый номер). The detail page renders the registered name, legal
  form, status, registered address, OKPO code, charter capital, and
  manager / first signatory. No authentication, no JSON contract — pure
  HTML scrape.
* https://sti.gov.kg/ — State Tax Service (ГНС). VAT-payer validator
  pages exist but are session-bound and partial; not relied on.
* https://www.kse.kg/ — Kyrgyz Stock Exchange. Free listing pages cover
  a handful of issuers; no per-INN reverse lookup and no central
  financial-statement registry, so `fetch_financials` returns [] rather
  than fabricating filings.

Identifier:
- INN (ИНН) — 14 digits for corporate taxpayers. The same number serves
  as the tax ID, the VAT registration ID, and the registry primary key.
  Both VAT and COMPANY_NUMBER identifier types map to the INN — callers
  may legitimately hand us either label.
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
    Director,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_INN_RE = re.compile(r"^\d{14}$")

# Kyrgyzaltyn OJSC — long-running state gold producer, used as liveness probe.
_HEALTH_PROBE_INN = "01410199810177"

# Field labels Min Justice may render in Russian or Kyrgyz. Matching is
# case-insensitive and stripped of trailing colons.
_LABEL_NAME = (
    "наименование",
    "полное наименование",
    "название",
    "аталышы",
    "толук аталышы",
    "name",
)
_LABEL_LEGAL_FORM = (
    "организационно-правовая форма",
    "правовая форма",
    "опф",
    "укуктук формасы",
    "legal form",
)
_LABEL_STATUS = (
    "статус",
    "состояние",
    "абалы",
    "status",
)
_LABEL_ADDRESS = (
    "адрес",
    "юридический адрес",
    "почтовый адрес",
    "дареги",
    "юридикалык дареги",
    "address",
)
_LABEL_CAPITAL = (
    "уставный капитал",
    "уставной капитал",
    "капитал",
    "уставдык капитал",
    "капиталы",
    "capital",
)
_LABEL_REG_DATE = (
    "дата регистрации",
    "дата перерегистрации",
    "дата создания",
    "катталган күнү",
    "registration date",
)
_LABEL_INN = (
    "инн",
    "идентификационный налоговый номер",
    "ssно",
    "снн",
)
_LABEL_OKPO = (
    "окпо",
    "okpo",
)
_LABEL_DIRECTOR = (
    "руководитель",
    "первый руководитель",
    "директор",
    "генеральный директор",
    "председатель",
    "жетекчи",
    "директору",
    "башчысы",
    "director",
    "manager",
    "head",
)

_STATUS_ACTIVE_TOKENS = (
    "действующ",  # действующий / действующее
    "активн",
    "active",
    "registered",
)
_STATUS_INACTIVE_TOKENS = (
    "ликвидир",
    "закрыт",
    "прекращ",
    "приостанов",
    "банкрот",
    "liquidated",
    "closed",
    "suspended",
    "inactive",
    "dissolved",
)


def _normalize_inn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("KG"):
        cleaned = cleaned[2:]
    if not _INN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kyrgyzstan INN must be exactly 14 digits, got: {value}"
        )
    return cleaned


def _parse_kg_date(value: str | None) -> date | None:
    """Min Justice renders dates as DD.MM.YYYY; tolerate ISO and slashes too."""
    if not value:
        return None
    s = str(value).strip()
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
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _parse_capital(raw: str | None) -> tuple[float | None, str | None]:
    """Pull an amount + currency out of a free-form charter-capital string.

    Min Justice records capital like "100 000,00 сом" or "5 000 000 KGS";
    the parser tolerates thousand separators (space or dot) and decimal
    commas alike.
    """
    if not raw:
        return None, None
    currency: str | None = None
    if re.search(r"\b(KGS|kgs|сом|сому|сомов|сом\.?)", raw, re.IGNORECASE):
        currency = "KGS"
    elif re.search(r"\bUSD\b|долл", raw, re.IGNORECASE):
        currency = "USD"
    elif re.search(r"\bEUR\b|евро", raw, re.IGNORECASE):
        currency = "EUR"
    elif re.search(r"\bRUB\b|руб", raw, re.IGNORECASE):
        currency = "RUB"

    digits = re.sub(r"[^\d,.\s]", "", raw).strip()
    if not digits:
        return None, currency
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


class KGAdapter(CountryAdapter):
    country_code = "KG"
    country_name = "Kyrgyzstan"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://register.minjust.gov.kg"
    REGISTER_PATH = "/register/"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru,ky;q=0.8,en;q=0.6",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    self.REGISTER_PATH,
                    params={"inn": _HEALTH_PROBE_INN},
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
                notes=f"register.minjust.gov.kg unreachable: {exc}"[:200],
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
                    "register.minjust.gov.kg responded but probe INN returned "
                    "no structured fields; portal markup may have changed."
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
                "Name search + INN lookup via Min Justice HTML. No "
                "centralized free financial dataset."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        params = {"name": name}
        async with self._client() as client:
            resp = await get_with_retry(
                client, self.REGISTER_PATH, params=params
            )
            resp.raise_for_status()
            page_text = _decode_response(resp)

        results = _extract_search_results(page_text)
        out: list[CompanyMatch] = []
        for item in results[:limit]:
            inn = item.get("id")
            if not inn:
                continue
            out.append(
                CompanyMatch(
                    id=inn,
                    name=item.get("name", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT,
                            value=inn,
                            label="INN",
                        ),
                    ],
                    address=item.get("address"),
                    status=_classify_status(item.get("status_raw")),
                    source_url=f"{self.BASE_URL}{self.REGISTER_PATH}?inn={inn}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                "Kyrgyzstan adapter accepts only VAT or COMPANY_NUMBER "
                f"(14-digit INN), got {id_type}"
            )
        inn = _normalize_inn(value)
        params = {"inn": inn}
        async with self._client() as client:
            resp = await get_with_retry(
                client, self.REGISTER_PATH, params=params
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
                for token in ("not found", "не найден", "табылган жок")
            ):
                return None
            return None

        capital_amount, capital_currency = _parse_capital(record.get("capital"))
        directors = [
            Director(name=d) for d in record.get("directors", []) if d
        ]
        source_url = f"{self.BASE_URL}{self.REGISTER_PATH}?inn={inn}"

        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=inn,
                label="INN",
            ),
        ]
        okpo = record.get("okpo")
        if okpo:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=str(okpo),
                    label="OKPO",
                )
            )

        return CompanyDetails(
            id=inn,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_kg_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=capital_amount,
            capital_currency=capital_currency or "KGS",
            identifiers=identifiers,
            directors=directors,
            raw={
                "source": "register.minjust.gov.kg",
                "fields": record,
            },
            source_url=source_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Kyrgyzstan has no centralized free corporate-financial dataset.
        # The Min Justice register stores administrative facts only; the
        # Kyrgyz Stock Exchange (kse.kg) publishes a limited issuer list
        # but exposes no per-INN reverse lookup and no machine-readable
        # filings index. Spec rule 1 forbids fabricating filings, so we
        # validate the INN and return [] honestly.
        _normalize_inn(company_id)
        return []


def _decode_response(resp: httpx.Response) -> str:
    """Decode the response body as text, preferring UTF-8 then cp1251.

    Min Justice serves UTF-8 today, but Cyrillic registries in the region
    have historically shipped cp1251 / windows-1251; tolerate both before
    falling back to httpx's guess.
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
    """Pull the legal-entity fields out of a Min Justice detail page."""
    if not html:
        return {}

    parser = _CellParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("KG minjust HTML parse failed: %s", exc)
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
        elif "okpo" not in record and _match_label(label_cell, _LABEL_OKPO):
            record["okpo"] = value_cell
        elif _match_label(label_cell, _LABEL_DIRECTOR):
            if value_cell not in directors:
                directors.append(value_cell)

    if directors:
        record["directors"] = directors
    return record


_RESULT_LINK_RE = re.compile(
    r"inn=(\d{14})[^>]*>\s*([^<]+?)\s*<", re.IGNORECASE
)


def _extract_search_results(html: str) -> list[dict[str, Any]]:
    """Pull (INN, name) tuples out of the result-list HTML.

    Min Justice renders each match as a row whose first cell is an
    anchor pointing back to `?inn=<14 digits>`. We extract those plus
    any adjacent address/status cells. The parser is forgiving: if the
    layout changes, callers fall back to looking up known INNs directly.
    """
    if not html:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _RESULT_LINK_RE.finditer(html):
        inn = match.group(1)
        if inn in seen:
            continue
        seen.add(inn)
        name = unescape(match.group(2)).strip()
        out.append({"id": inn, "name": name})

    if out:
        return out

    # Fallback: scan flattened table cells for any 14-digit INN and pair
    # it with the preceding name cell.
    parser = _CellParser()
    try:
        parser.feed(html)
    except Exception:
        return out
    cells = [c for c in parser.cells if c]
    for idx, cell in enumerate(cells):
        compact = cell.replace(" ", "")
        if _INN_RE.match(compact) and compact not in seen:
            seen.add(compact)
            name = cells[idx - 1] if idx > 0 else ""
            out.append({"id": compact, "name": name})
    return out
