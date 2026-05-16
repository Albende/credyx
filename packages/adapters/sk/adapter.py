"""Slovakia adapter — ORSR (Obchodný register SR) + RÚZ (Register účtovných závierok).

Two free, public, no-auth sources are combined:

- **ORSR** (https://www.orsr.sk/) — court business register. Only HTML, served
  in `windows-1250`. Used for name search and for the canonical "company
  extract" URL (`vypis.asp?ID=...&SID=...&P=0`). ORSR has no public API and
  no useful structured JSON.
- **RÚZ** (https://www.registeruz.sk/cruz-public/) — Register of Financial
  Statements. Open JSON REST API at `/cruz-public/api/`. Returns the
  accounting-unit record (with `ico`, `dic`, name, address, NACE, legal
  form code, incorporation date) plus the list of every filed annual
  financial statement and annual report. PDFs are public at
  `/cruz-public/domain/financialreport/pdf/{id}`.

The RÚZ JSON is preferred for `lookup_by_identifier` because the ORSR
extract is windows-1250 HTML with no stable id attributes. ORSR is still
used for `search_by_name` (RÚZ name search is fuzzy and slow).
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_ICO_RE = re.compile(r"^\d{8}$")
_DIC_RE = re.compile(r"^\d{10}$")
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

# ORSR search-result row: name link is `<a href="vypis.asp?ID=NNN&SID=N&P=0" ...>NAME</a>`.
# The page is one big table of these per match; we extract id + sid + display name.
_ORSR_ROW_RE = re.compile(
    r'<a\s+href="vypis\.asp\?ID=(?P<id>\d+)&(?:amp;)?SID=(?P<sid>\d+)&(?:amp;)?P=0"'
    r'[^>]*>(?P<name>[^<]+)</a>',
    re.IGNORECASE,
)
# IČO row inside an ORSR vypis.asp extract — IČO is rendered with thin spaces:
#   <span class="tl">IČO:&nbsp;</span> ... <span class='ra'>  35 757 442 </span>
_ORSR_VYPIS_ICO_RE = re.compile(
    r"I[ČC]O:.*?<span[^>]*>\s*([\d\s]{8,12})\s*</span>",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_ico(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.upper().startswith("SK"):
        cleaned = cleaned[2:]
    if cleaned.isdigit() and len(cleaned) < 8:
        cleaned = cleaned.zfill(8)
    if not _ICO_RE.match(cleaned):
        raise InvalidIdentifierError(f"SK IČO must be 8 digits, got: {value}")
    return cleaned


def _normalize_vat(value: str) -> str:
    cleaned = value.strip().replace(" ", "").upper()
    if cleaned.startswith("SK"):
        cleaned = cleaned[2:]
    if not _DIC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"SK VAT/DIČ must be 10 digits (optionally SK-prefixed), got: {value}"
        )
    return cleaned


class SKAdapter(CountryAdapter):
    country_code = "SK"
    country_name = "Slovakia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    ORSR_BASE = "https://www.orsr.sk"
    RUZ_BASE = "https://www.registeruz.sk/cruz-public"
    # 2000-01-01 is well before the RÚZ system existed, so passing it as
    # `zmenene-od` effectively means "return everything ever filed". The
    # parameter is required by the API but otherwise pointless for a single-
    # IČO lookup.
    RUZ_ALL_TIME = "2000-01-01"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.ORSR_BASE) as client:
                resp = await get_with_retry(client, "/default.asp")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"ORSR probe failed: {str(exc)[:180]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "ORSR HTML scrape (windows-1250) for name search; "
                "RÚZ JSON API for IČO/DIČ lookup and financial filings."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.ORSR_BASE) as client:
            resp = await get_with_retry(
                client,
                "/hladaj_subjekt.asp",
                params={"OBMENO": name, "PF": "0", "SID": "0", "R": "on"},
            )
            resp.raise_for_status()
            page = _decode_orsr(resp.content, resp.encoding)

        seen: set[str] = set()
        matches: list[CompanyMatch] = []
        for m in _ORSR_ROW_RE.finditer(page):
            sid = m.group("sid")
            internal_id = m.group("id")
            key = f"{internal_id}:{sid}"
            if key in seen:
                continue
            seen.add(key)
            display_name = html.unescape(m.group("name")).strip()
            if not display_name:
                continue
            matches.append(
                CompanyMatch(
                    id=internal_id,
                    name=display_name,
                    country=self.country_code,
                    identifiers=[],
                    source_url=f"{self.ORSR_BASE}/vypis.asp?ID={internal_id}&SID={sid}&P=0",
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            target_ico = _normalize_ico(value)
            target_dic: str | None = None
            params = {"ico": target_ico}
        elif id_type == IdentifierType.VAT:
            target_dic = _normalize_vat(value)
            target_ico = None
            params = {"dic": target_dic}
        else:
            raise InvalidIdentifierError(
                f"SK supports COMPANY_NUMBER (IČO) or VAT (DIČ), got {id_type}"
            )

        async with build_http_client(base_url=self.RUZ_BASE) as client:
            list_resp = await get_with_retry(
                client,
                "/api/uctovne-jednotky",
                params={**params, "zmenene-od": self.RUZ_ALL_TIME, "max-zaznamov": 10},
            )
            list_resp.raise_for_status()
            id_list = [int(x) for x in (list_resp.json().get("id") or [])]
            if not id_list:
                return None
            entity = await _pick_live_entity(client, id_list, target_ico, target_dic)

        if entity is None:
            return None
        return _details_from_ruz(entity, self.ORSR_BASE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ico = _normalize_ico(company_id)
        async with build_http_client(base_url=self.RUZ_BASE) as client:
            list_resp = await get_with_retry(
                client,
                "/api/uctovne-jednotky",
                params={"ico": ico, "zmenene-od": self.RUZ_ALL_TIME, "max-zaznamov": 10},
            )
            list_resp.raise_for_status()
            id_list = [int(x) for x in (list_resp.json().get("id") or [])]
            if not id_list:
                return []
            entity = await _pick_live_entity(client, id_list, ico, None)
            if entity is None:
                return []
            entity_id = int(entity.get("id") or 0)

            filing_ids = [int(x) for x in (entity.get("idUctovnychZavierok") or [])]
            if not filing_ids:
                return []

            cutoff_year = datetime.utcnow().year - years
            filings: list[FinancialFiling] = []
            for fid in filing_ids:
                f_resp = await get_with_retry(
                    client, "/api/uctovna-zavierka", params={"id": fid}
                )
                if f_resp.status_code != 200:
                    continue
                f = f_resp.json()
                period_end = _parse_date(f.get("datumZostaveniaK") or f.get("obdobieDo"))
                year = period_end.year if period_end else _year_from_period(f.get("obdobieDo"))
                if year is None or year < cutoff_year:
                    continue
                filings.append(
                    FinancialFiling(
                        company_id=ico,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=period_end,
                        currency="EUR",
                        structured_data=None,
                        document_url=f"{self.RUZ_BASE}/domain/financialreport/pdf/{fid}",
                        document_format="pdf",
                        source_url=(
                            f"https://www.registeruz.sk/cruz-public/uctovna-jednotka/"
                            f"{entity_id}/zavierka/{fid}"
                        ),
                    )
                )

        # Newest first — easier for the risk engine to pick the most
        # recent period at the head of the list.
        filings.sort(key=lambda f: (f.period_end or date.min), reverse=True)
        return filings


async def _pick_live_entity(
    client: Any,
    id_list: list[int],
    target_ico: str | None,
    target_dic: str | None,
) -> dict[str, Any] | None:
    """Resolve a list of RÚZ entity-ids to a single live (non-deleted) record.

    The `/api/uctovne-jednotky` ID-list endpoint returns *every* accounting
    unit that has ever existed under an IČO, including ones marked deleted
    (`stav: ZMAZANÉ`) with no `ico`/`nazovUJ`. We fetch each detail, drop the
    deleted ones, and prefer the entry whose `ico`/`dic` exactly matches the
    requested identifier. Falls back to the first non-deleted record.
    """
    live: list[dict[str, Any]] = []
    for entity_id in sorted(id_list):
        resp = await get_with_retry(
            client, "/api/uctovna-jednotka", params={"id": entity_id}
        )
        if resp.status_code != 200:
            continue
        data = resp.json()
        stav = str(data.get("stav") or "").strip().upper()
        if stav and "ZMAZAN" in stav:
            continue
        if not (data.get("ico") or data.get("nazovUJ")):
            continue
        live.append(data)

    if not live:
        return None
    if target_ico:
        for d in live:
            if str(d.get("ico") or "").strip() == target_ico:
                return d
    if target_dic:
        for d in live:
            if str(d.get("dic") or "").strip() == target_dic:
                return d
    return live[0]


def _decode_orsr(content: bytes, declared_encoding: str | None) -> str:
    """Decode an ORSR HTTP response.

    ORSR serves `Content-Type: text/html; charset=windows-1250`. httpx
    usually picks this up via `response.text`, but the encoding header is
    sometimes missing on intermediate redirects — fall back to cp1250
    explicitly so Slovak diacritics survive.
    """
    for enc in (declared_encoding, "windows-1250", "utf-8"):
        if not enc:
            continue
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("windows-1250", errors="replace")


def _details_from_ruz(data: dict[str, Any], orsr_base: str) -> CompanyDetails:
    ico = str(data.get("ico") or "").strip()
    dic = str(data.get("dic") or "").strip() or None
    name = (data.get("nazovUJ") or "").strip()
    address = _format_ruz_address(data)

    identifiers: list[RegistryIdentifier] = []
    if ico:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=ico, label="IČO")
        )
    if dic and _DIC_RE.match(dic):
        # RÚZ exposes DIČ; the VAT (IČ DPH) form is DIČ prefixed with SK,
        # which is the format used downstream for VIES checks.
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.VAT, value=f"SK{dic}", label="IČ DPH / DIČ")
        )

    sk_nace = data.get("skNace")
    nace_codes = [str(sk_nace)] if sk_nace else []

    legal_form_code = data.get("pravnaForma")
    legal_form = _SK_LEGAL_FORM.get(str(legal_form_code)) if legal_form_code else None

    return CompanyDetails(
        id=ico,
        name=name,
        country="SK",
        legal_form=legal_form,
        status=None,
        incorporation_date=_parse_date(data.get("datumZalozenia")),
        registered_address=address,
        capital_currency="EUR",
        nace_codes=nace_codes,
        identifiers=identifiers,
        raw=data,
        source_url=f"{orsr_base}/hladaj_ico.asp?ICO={ico}&SID=0" if ico else None,
    )


def _format_ruz_address(d: dict[str, Any]) -> str | None:
    parts = [
        d.get("ulica"),
        f"{d.get('psc', '').strip()} {d.get('mesto', '').strip()}".strip() or None,
    ]
    parts = [str(p).strip() for p in parts if p]
    return ", ".join(parts) if parts else None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    raw = str(s).strip()
    # Try common formats RÚZ returns: full ISO date, year-month only
    # (e.g. period markers), and the dotted Slovak form.
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _year_from_period(period: str | None) -> int | None:
    if not period:
        return None
    try:
        return int(str(period)[:4])
    except ValueError:
        return None


# Slovak legal-form codes used by RÚZ (`pravnaForma`). Only the most common
# commercial forms are mapped — anything else falls through to the raw code
# so we never invent a label we can't justify.
_SK_LEGAL_FORM = {
    "111": "Verejná obchodná spoločnosť",
    "112": "Komanditná spoločnosť",
    "113": "Spoločnosť s ručením obmedzeným",
    "121": "Akciová spoločnosť",
    "122": "Jednoduchá spoločnosť na akcie",
    "205": "Družstvo",
    "301": "Štátny podnik",
    "421": "Európske zoskupenie hospodárskych záujmov",
    "422": "Európska spoločnosť (SE)",
    "423": "Európske družstvo",
    "701": "Združenie",
    "751": "Spoločenstvo vlastníkov bytov",
    "801": "Obec",
    "802": "Vyšší územný celok",
}
