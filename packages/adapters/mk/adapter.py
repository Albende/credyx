"""North Macedonia adapter — Central Registry (CRM) + Macedonian Stock Exchange.

Sources (all free, no auth):

* Central Registry of the Republic of North Macedonia — public portal at
  ``https://www.crm.com.mk/`` with a free basic-search front-end at
  ``https://e-submit.crm.com.mk/``. The portal renders Cyrillic
  Macedonian (and Latin transliterations) and exposes per-entity detail
  pages with: name, EMBS, EDB, address, primary activity (NACE), legal
  form, status, share capital.
* Macedonian Stock Exchange (MSE) — ``https://www.mse.mk/`` publishes the
  annual reports of listed issuers free of charge. Filings are PDFs;
  this adapter surfaces deep-links by year, leaving PDF text extraction
  to the cross-cutting worker.

Identifiers:

* EMBS (Embeded Subject Number, 7 digits) — Central Registry primary key.
  Mapped to ``IdentifierType.COMPANY_NUMBER``.
* EDB (Edinstven daneken broj, 13 digits, legal entities start with ``4080``
  region code — practically ``4030`` or ``4080`` prefixes depending on
  jurisdiction). Tax / VAT identifier. Mapped to ``IdentifierType.VAT``.

The CRM portal is a server-rendered ASP.NET app without a public JSON
contract. We scrape conservatively, never invent fields, and fall back
to a minimal ``CompanyDetails`` carrying the identifier plus a deep-link
when the page markup shifts. Returning fabricated names or numbers
would violate the project rule against mock data.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

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

logger = logging.getLogger(__name__)

_EMBS_RE = re.compile(r"^\d{7}$")
_EDB_RE = re.compile(r"^\d{13}$")
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_EMBS_IN_TEXT_RE = re.compile(r"(?<!\d)\d{7}(?!\d)")
_EDB_IN_TEXT_RE = re.compile(r"(?<!\d)\d{13}(?!\d)")

# Komercijalna Banka AD Skopje — a stable, large, active issuer used as a
# portal liveness probe. Its EMBS is publicly known.
_HEALTH_PROBE_EMBS = "4068916"

# Field labels CRM renders in Macedonian Cyrillic / Latin transliteration.
_LABEL_NAME = (
    "назив",
    "naziv",
    "име",
    "ime",
    "субјект",
    "subjekt",
    "company",
    "name",
)
_LABEL_LEGAL_FORM = (
    "правна форма",
    "pravna forma",
    "форма",
    "forma",
    "legal form",
)
_LABEL_STATUS = (
    "статус",
    "status",
    "состојба",
    "sostojba",
)
_LABEL_ADDRESS = (
    "седиште",
    "sediste",
    "адреса",
    "adresa",
    "address",
)
_LABEL_EMBS = ("ембс", "embs")
_LABEL_EDB = ("едб", "edb", "danocen", "даночен")
_LABEL_INCORP = (
    "датум на регистрација",
    "datum na registracija",
    "датум на основање",
    "datum na osnovanje",
    "регистриран на",
    "registriran na",
)
_LABEL_CAPITAL = (
    "основна главнина",
    "osnovna glavnina",
    "капитал",
    "kapital",
    "уписан капитал",
    "upisan kapital",
)
_LABEL_ACTIVITY = (
    "приоритетна дејност",
    "prioritetna dejnost",
    "дејност",
    "dejnost",
    "шифра",
    "sifra",
)

_STATUS_ACTIVE_TOKENS = ("активен", "aktiven", "активна", "aktivna", "active")
_STATUS_CEASED_TOKENS = (
    "избришан",
    "izbrisan",
    "ликвидиран",
    "likvidiran",
    "стечај",
    "stecaj",
    "престанал",
    "prestanal",
    "престаната",
    "prestanata",
)


def _normalize_embs(value: str) -> str:
    """Strip whitespace/separators and validate or left-pad to 7 digits."""
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not cleaned.isdigit() or len(cleaned) > 7 or not cleaned:
        raise InvalidIdentifierError(
            f"Macedonian EMBS must be up to 7 digits, got: {value}"
        )
    padded = cleaned.zfill(7)
    if not _EMBS_RE.match(padded):
        raise InvalidIdentifierError(
            f"Macedonian EMBS must be exactly 7 digits, got: {value}"
        )
    return padded


def _normalize_edb(value: str) -> str:
    """Strip optional ``MK`` prefix and separators, validate to 13 digits."""
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("MK"):
        cleaned = cleaned[2:]
    if not _EDB_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Macedonian EDB must be exactly 13 digits, got: {value}"
        )
    return cleaned


def _parse_mk_date(value: str | None) -> date | None:
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


class MKAdapter(CountryAdapter):
    country_code = "MK"
    country_name = "North Macedonia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CRM_BASE = "https://www.crm.com.mk"
    ESUBMIT_BASE = "https://e-submit.crm.com.mk"
    MSE_BASE = "https://www.mse.mk"

    SEARCH_PATH = "/Search/Search"

    def _client(self, *, base_url: str | None = None, timeout: float = 30.0) -> httpx.AsyncClient:
        # CRM serves UTF-8 Macedonian Cyrillic with occasional cp1251 legacy
        # pages, mirrored by the encoding probe in `_decode_response`.
        return build_http_client(
            base_url=base_url or self.CRM_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "Accept-Language": "mk,en;q=0.7",
            },
            timeout=timeout,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client(base_url=self.CRM_BASE, timeout=20.0) as client:
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
                notes=f"CRM portal probe failed: {str(exc)[:160]}",
            )
        ok_signal = (
            "crm" in page_text.lower()
            or "централен регистар" in page_text.lower()
            or "centralen registar" in page_text.lower()
        )
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
                    "CRM portal reachable but expected markers missing; "
                    "search results parsing may be partial."
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
                "CRM portal HTML scrape for registry data; MSE deep-link for "
                "annual reports of listed issuers only. No XBRL/structured "
                "filings available — PDF text extraction is deferred."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        async with self._client(base_url=self.ESUBMIT_BASE) as client:
            try:
                resp = await get_with_retry(
                    client,
                    self.SEARCH_PATH,
                    params={"q": name},
                )
            except Exception as exc:
                logger.warning("CRM search transport error for %r: %s", name, exc)
                return []
            if resp.status_code >= 500:
                return []
            try:
                resp.raise_for_status()
            except Exception:
                return []
            page_text = _decode_response(resp)

        records = _parse_search_results(page_text)
        out: list[CompanyMatch] = []
        for rec in records[:limit]:
            embs = rec.get("embs")
            edb = rec.get("edb")
            if not embs and not edb and not rec.get("name"):
                continue
            idents: list[RegistryIdentifier] = []
            if embs:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=embs,
                        label="EMBS",
                    )
                )
            if edb:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=edb,
                        label="EDB",
                    )
                )
            out.append(
                CompanyMatch(
                    id=embs or edb or "",
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
            embs = _normalize_embs(value)
            query = embs
            edb: str | None = None
        elif id_type == IdentifierType.VAT:
            edb = _normalize_edb(value)
            query = edb
            embs = None
        else:
            raise InvalidIdentifierError(
                f"North Macedonia supports COMPANY_NUMBER (EMBS) or VAT "
                f"(EDB), got {id_type}"
            )

        async with self._client(base_url=self.ESUBMIT_BASE) as client:
            try:
                resp = await get_with_retry(
                    client,
                    self.SEARCH_PATH,
                    params={"q": query},
                )
            except Exception as exc:
                logger.warning("CRM lookup transport error for %s: %s", query, exc)
                return None
            if resp.status_code == 404:
                return None
            try:
                resp.raise_for_status()
            except Exception:
                return None
            page_text = _decode_response(resp)

        record = _pick_record(
            _parse_search_results(page_text),
            embs=embs,
            edb=edb,
        )
        if record is None:
            return None

        resolved_embs = record.get("embs") or embs
        resolved_edb = record.get("edb") or edb

        identifiers: list[RegistryIdentifier] = []
        if resolved_embs:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=resolved_embs,
                    label="EMBS",
                )
            )
        if resolved_edb:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=resolved_edb,
                    label="EDB",
                )
            )

        capital_amount, capital_currency = _parse_capital(record.get("capital"))

        return CompanyDetails(
            id=resolved_embs or resolved_edb or "",
            name=record.get("name", "").strip(),
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=_classify_status(record.get("status_raw")),
            incorporation_date=_parse_mk_date(record.get("incorporation_date")),
            registered_address=record.get("address"),
            capital_amount=capital_amount,
            capital_currency=capital_currency,
            nace_codes=[record["activity_code"]] if record.get("activity_code") else [],
            identifiers=identifiers,
            raw={"source": "crm.com.mk", "fields": record},
            source_url=self._search_url(query),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        embs = _normalize_embs(company_id)
        # MSE publishes annual reports only for listed issuers. We attempt the
        # public issuer search page; any non-listed company will simply yield
        # no filings. Returning [] is the contractually correct result.
        async with self._client(base_url=self.MSE_BASE, timeout=30.0) as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/en/issuers/issuers",
                    params={"search": embs},
                )
            except Exception as exc:
                logger.warning("MSE issuer search transport error for EMBS %s: %s", embs, exc)
                return []
            if resp.status_code in (404, 500):
                return []
            try:
                resp.raise_for_status()
            except Exception:
                return []
            page_text = _decode_response(resp)

        years_found = _parse_filing_years(page_text)
        if not years_found:
            return []
        cutoff = max(years_found) - years
        filings: list[FinancialFiling] = []
        for y in sorted(years_found, reverse=True):
            if y < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=embs,
                    year=y,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(y, 12, 31),
                    currency="MKD",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=f"{self.MSE_BASE}/en/issuers/issuers?search={embs}",
                )
            )
        return filings

    def _search_url(self, text: str) -> str:
        return (
            f"{self.ESUBMIT_BASE}{self.SEARCH_PATH}?q={quote(text, safe='')}"
        )


def _decode_response(resp) -> str:
    """Decode response bytes preferring UTF-8 then cp1251 (legacy Macedonian Cyrillic)."""
    body = resp.content
    if not body:
        return ""
    for encoding in ("utf-8", "cp1251", "windows-1251", "cp1250"):
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
    """Best-effort extraction of company rows from the CRM e-submit HTML.

    The portal renders results in one of two shapes depending on context —
    a single-record table with ``label/value`` rows, or a multi-row card list.
    We accept either: harvest every ``<td>`` cell, walk pairwise looking for
    canonical labels, and additionally scan loose text for EMBS / EDB tokens
    so a row missing structured labels still gives us identifiers.
    """
    if not html:
        return []

    parser = _CellParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.warning("MK CRM HTML parse failed: %s", exc)
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
        elif "embs" not in record and _match_label(label_cell, _LABEL_EMBS):
            m = _EMBS_IN_TEXT_RE.search(value_cell)
            if m:
                record["embs"] = m.group(0)
        elif "edb" not in record and _match_label(label_cell, _LABEL_EDB):
            m = _EDB_IN_TEXT_RE.search(value_cell)
            if m:
                record["edb"] = m.group(0)
        elif "incorporation_date" not in record and _match_label(label_cell, _LABEL_INCORP):
            record["incorporation_date"] = value_cell
        elif "capital" not in record and _match_label(label_cell, _LABEL_CAPITAL):
            record["capital"] = value_cell
        elif "activity_code" not in record and _match_label(label_cell, _LABEL_ACTIVITY):
            code_match = re.search(r"\d{2,5}", value_cell)
            if code_match:
                record["activity_code"] = code_match.group(0)

    if not record.get("embs") or not record.get("edb"):
        flat = _strip_html(html)
        if not record.get("embs"):
            m = _EMBS_IN_TEXT_RE.search(flat)
            if m:
                record["embs"] = m.group(0)
        if not record.get("edb"):
            m = _EDB_IN_TEXT_RE.search(flat)
            if m:
                record["edb"] = m.group(0)

    if not (record.get("embs") or record.get("edb") or record.get("name")):
        return []
    return [record]


def _pick_record(
    records: list[dict[str, Any]],
    *,
    embs: str | None,
    edb: str | None,
) -> dict[str, Any] | None:
    if not records:
        return None
    if embs:
        for r in records:
            if r.get("embs") == embs:
                return r
    if edb:
        for r in records:
            if r.get("edb") == edb:
                return r
    return records[0] if records else None


def _parse_capital(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    text = value.strip()
    currency = None
    for token, code in (
        ("MKD", "MKD"),
        ("ден", "MKD"),
        ("den", "MKD"),
        ("EUR", "EUR"),
        ("евро", "EUR"),
        ("USD", "USD"),
    ):
        if token.lower() in text.lower():
            currency = code
            break
    m = re.search(r"([\d][\d\s.,]*)", text)
    if not m:
        return None, currency
    # CRM renders amounts in Macedonian locale: "1.234.567,89" → "1234567.89".
    # Strip thousands dots first, then map decimal comma; robust to either
    # "1.234.567,89" or "1234567,89".
    raw = m.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw), (currency or "MKD")
    except ValueError:
        return None, currency


def _parse_filing_years(html: str) -> list[int]:
    """Extract distinct reporting years referenced on an MSE issuer page."""
    stripped = _strip_html(html)
    years: set[int] = set()
    current_year = date.today().year
    for match in _YEAR_RE.finditer(stripped):
        y = int(match.group(0))
        # MSE electronic-disclosure archive starts around 2005; clip lower bound
        # to avoid stray years embedded in addresses or footer copy.
        if 2005 <= y <= current_year:
            years.add(y)
    return sorted(years)
