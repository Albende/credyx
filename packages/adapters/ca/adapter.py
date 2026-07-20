"""Canada adapter — Corporations Canada (federal register JSON API) + SEC EDGAR.

Two free public sources, no API key required:

- **Corporations Canada** (Innovation, Science and Economic Development Canada)
  hosts the federal corporations register. Name search POSTs to the public
  search form ``/cc/lgcy/fdrlCrpSrch.html`` (results are server-rendered HTML
  rows linking to ``fdrlCrpDtls.html?corpId=N``). Full structured records come
  from the register's own JSON API,
  ``/cc/lgcy/api/corporations/{corporationId}.json?lang=eng`` — the *same*
  endpoint also resolves a 9-digit Business Number. The public plan allows 60
  hits/min. A not-found id returns HTTP 200 with a two-string array, not a 404.
- **SEC EDGAR** for financial filings. Large Canadian issuers cross-list on US
  exchanges and file their annual reports with the SEC (40-F / 20-F for foreign
  private issuers, 10-K for domestic filers). EDGAR exposes these for free via
  the submissions JSON API. Companies that file only on SEDAR+ (bot-walled,
  undocumented, out of MVP scope) return no filings here.

Coverage caveat: the federal register covers only federally incorporated
entities (~1/3 of Canadian companies). Provincial registries (ON/QC/BC/AB) are
paid per-jurisdiction services and out of scope. OpenCorporates is a resilience
fallback for name search — it sometimes has provincially-registered hits.

Identifier formats:
- Corporation Number: the register's ``corporationId`` — bare digits (5–8),
  historically displayed with a cosmetic trailing check digit (``426160-7``).
  We strip the separator and validate digits-only.
- Business Number (BN): 9 digits, optionally + 2-letter program + 4-digit
  reference (e.g. ``847871746RC0001``). Surfaced as a ``VAT`` identifier and
  resolvable via the same register JSON endpoint on its 9-digit stem.
"""
from __future__ import annotations

import html
import logging
import os
import re
from asyncio import Lock
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.adapters._global.opencorporates import OpenCorporatesClient
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

_CORP_NUM_RE = re.compile(r"^\d{4,9}$")
_BN_RE = re.compile(r"^\d{9}(?:[A-Z]{2}\d{4})?$")

# SEC EDGAR two-letter location codes for Canadian provinces/territories, plus
# the annual-report currency signal that a filer is a foreign private issuer.
_CA_STATE_CODES = {"A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "B0"}
_ANNUAL_FORMS = ("40-F", "20-F", "10-K")
_FOREIGN_ISSUER_FORMS = ("40-F", "20-F")

_LEGAL_SUFFIXES = re.compile(
    r"\b("
    r"incorporated|incorporee|incorporée|inc|"
    r"corporation|corp|"
    r"limited|limitee|limitée|ltd|ltee|ltée|"
    r"company|compagnie|co|"
    r"ulc|lp|llp|holdings?"
    r")\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_corp_number(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if not _CORP_NUM_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Canadian Corporation Number invalid (expected 4–9 digits): {value}"
        )
    return cleaned


def _normalize_bn(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if not _BN_RE.match(cleaned):
        raise InvalidIdentifierError(
            "Canadian Business Number invalid (expected 9 digits, optionally "
            f"+ 2 letters + 4 digits): {value}"
        )
    return cleaned[:9]


def _name_key(name: str) -> str:
    """Collapse a company name to a suffix-free comparison key."""
    stripped = _LEGAL_SUFFIXES.sub(" ", name.lower())
    return _NON_ALNUM.sub("", stripped)


class CAAdapter(CountryAdapter):
    country_code = "CA"
    country_name = "Canada"
    identifier_types = [
        IdentifierType.COMPANY_NUMBER,  # federal Corporation Number (corporationId)
        IdentifierType.VAT,             # Business Number (BN9)
        IdentifierType.OTHER,
    ]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 60

    CC_BASE = "https://ised-isde.canada.ca"
    CC_SEARCH_PATH = "/cc/lgcy/fdrlCrpSrch.html"
    CC_DETAILS_PATH = "/cc/lgcy/fdrlCrpDtls.html"
    CC_API_PATH = "/cc/lgcy/api/corporations/{}.json"

    EDGAR_BASE = "https://www.sec.gov"
    EDGAR_DATA_BASE = "https://data.sec.gov"

    _tickers_cache: list[dict[str, Any]] | None = None
    _tickers_lock = Lock()

    def __init__(self) -> None:
        self._oc = OpenCorporatesClient()
        contact = os.getenv("SEC_EDGAR_USER_AGENT", "Credyx dev contact@credyx.ai")
        self._sec_headers = {"User-Agent": contact, "Accept-Encoding": "gzip, deflate"}

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.CC_BASE) as client:
                resp = await get_with_retry(
                    client, self.CC_API_PATH.format("4261607"), params={"lang": "eng"}
                )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Federal corporations register JSON API for search + lookup. "
                "Financials via SEC EDGAR for US-cross-listed Canadian issuers; "
                "SEDAR+-only filers return no filings."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        matches = await self._search_corporations_canada(name, limit)
        if matches:
            return matches
        return await self._search_opencorporates(name, limit)

    async def _search_corporations_canada(
        self, name: str, limit: int
    ) -> list[CompanyMatch]:
        form = {
            "corpName": name,
            "corpNumber": "",
            "busNumber": "",
            "corpProvince": "",
            "corpStatus": "",
            "corpAct": "",
            "buttonNext": "Next",
        }
        try:
            async with build_http_client(base_url=self.CC_BASE) as client:
                resp = await client.post(
                    self.CC_SEARCH_PATH, params={"locale": "en_CA"}, data=form
                )
                if resp.status_code >= 400:
                    return []
                html_text = resp.text
        except Exception as exc:
            logger.warning("Corporations Canada search failed: %s", exc)
            return []

        out: list[CompanyMatch] = []
        for corp_id, display_name, status in _parse_cc_results(html_text):
            if len(out) >= limit:
                break
            out.append(
                CompanyMatch(
                    id=corp_id,
                    name=display_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=corp_id,
                            label="Corporation Number",
                        )
                    ],
                    address=None,
                    status=status,
                    source_url=f"{self.CC_BASE}{self.CC_DETAILS_PATH}?corpId={corp_id}",
                )
            )
        return out

    async def _search_opencorporates(
        self, name: str, limit: int
    ) -> list[CompanyMatch]:
        try:
            rows = await self._oc.search_companies(name, jurisdiction="ca", per_page=limit)
        except Exception as exc:
            logger.warning("OpenCorporates CA fallback failed: %s", exc)
            return []
        out: list[CompanyMatch] = []
        for r in rows[:limit]:
            cn = str(r.get("company_number") or "").strip()
            if not cn:
                continue
            out.append(
                CompanyMatch(
                    id=cn,
                    name=r.get("name", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=cn,
                            label="Corporation Number",
                        )
                    ],
                    address=r.get("registered_address_in_full"),
                    status=r.get("current_status"),
                    source_url=r.get("opencorporates_url"),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_federal(_normalize_corp_number(value))
        if id_type == IdentifierType.VAT:
            return await self._lookup_federal(_normalize_bn(value))
        if id_type == IdentifierType.OTHER:
            raise AdapterError(
                "CA OTHER identifier is reserved; look up by Corporation Number "
                "or Business Number instead."
            )
        raise InvalidIdentifierError(
            f"CA adapter supports COMPANY_NUMBER, VAT, OTHER; got {id_type}"
        )

    async def _lookup_federal(self, resource_id: str) -> CompanyDetails | None:
        try:
            async with build_http_client(base_url=self.CC_BASE) as client:
                resp = await get_with_retry(
                    client, self.CC_API_PATH.format(resource_id), params={"lang": "eng"}
                )
                if resp.status_code == 404:
                    return None
                if resp.status_code >= 400:
                    raise AdapterError(
                        f"Corporations Canada API returned {resp.status_code}"
                    )
                payload = resp.json()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Corporations Canada API fetch failed: {exc}") from exc

        record = _first_record(payload)
        if record is None:
            return None

        corp_id = str(record.get("corporationId") or resource_id)
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=corp_id,
                label="Corporation Number",
            )
        ]
        bn = (record.get("businessNumbers") or {}).get("businessNumber")
        if bn:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=str(bn), label="Business Number"
                )
            )

        status = record.get("status")
        return CompanyDetails(
            id=corp_id,
            name=_primary_name(record),
            country="CA",
            legal_form=record.get("act") or "Federal corporation",
            status=status.lower() if isinstance(status, str) else None,
            incorporation_date=_activity_date(record, ("Incorporation", "Amalgamation")),
            dissolution_date=_activity_date(record, ("Dissolution", "Revocation")),
            registered_address=_registered_address(record),
            identifiers=identifiers,
            raw=record,
            source_url=f"{self.CC_BASE}{self.CC_DETAILS_PATH}?corpId={corp_id}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        details = await self._lookup_federal(_normalize_corp_number(company_id))
        if not details or not details.name:
            return []
        cik = await self._match_edgar_cik(details.name)
        if cik is None:
            return []
        return await self._fetch_edgar_filings(cik, company_id, years)

    async def _load_tickers(self) -> list[dict[str, Any]]:
        async with CAAdapter._tickers_lock:
            if CAAdapter._tickers_cache is None:
                async with build_http_client(headers=self._sec_headers) as client:
                    resp = await get_with_retry(
                        client, f"{self.EDGAR_BASE}/files/company_tickers.json"
                    )
                    resp.raise_for_status()
                    CAAdapter._tickers_cache = list(resp.json().values())
            return CAAdapter._tickers_cache

    async def _match_edgar_cik(self, name: str) -> str | None:
        rows = await self._load_tickers()
        key = _name_key(name)
        if not key:
            return None
        for r in rows:
            if _name_key(str(r.get("title", ""))) == key:
                return str(r.get("cik_str", "")).zfill(10)
        return None

    async def _fetch_edgar_filings(
        self, cik: str, company_id: str, years: int
    ) -> list[FinancialFiling]:
        try:
            async with build_http_client(headers=self._sec_headers) as client:
                resp = await get_with_retry(
                    client, f"{self.EDGAR_DATA_BASE}/submissions/CIK{cik}.json"
                )
                if resp.status_code >= 400:
                    return []
                data = resp.json()
        except Exception as exc:
            logger.warning("EDGAR submissions fetch failed for CIK %s: %s", cik, exc)
            return []

        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        if not _is_canadian_filer(data, forms):
            return []

        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        report_dates = recent.get("reportDate") or []
        filing_dates = recent.get("filingDate") or []
        cutoff = datetime.utcnow().year - years
        cik_int = int(cik)

        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for form, acc, doc, report, filed in zip(
            forms, accessions, primary_docs, report_dates, filing_dates
        ):
            if form not in _ANNUAL_FORMS:
                continue
            period_end = _parse_iso_date(report)
            year = period_end.year if period_end else (_year_of(filed))
            if year is None or year < cutoff or year in seen_years:
                continue
            seen_years.add(year)
            acc_nodash = acc.replace("-", "")
            document_url = (
                f"{self.EDGAR_BASE}/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
                if doc else None
            )
            filings.append(
                FinancialFiling(
                    company_id=company_id,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency=None,
                    structured_data=None,
                    document_url=document_url,
                    document_format="html" if doc and doc.endswith((".htm", ".html")) else None,
                    source_url=(
                        f"{self.EDGAR_BASE}/cgi-bin/browse-edgar"
                        f"?action=getcompany&CIK={cik}&type={form}"
                    ),
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings


def _first_record(payload: Any) -> dict[str, Any] | None:
    """Return the corporation object from the register's two-element response.

    A not-found id yields ``["could not find ...", "..."]`` (both strings) with
    HTTP 200; a hit yields ``[{...}, null]`` for ``lang=eng``.
    """
    if isinstance(payload, list):
        for el in payload:
            if isinstance(el, dict) and el.get("corporationId"):
                return el
        return None
    if isinstance(payload, dict) and payload.get("corporationId"):
        return payload
    return None


def _primary_name(record: dict[str, Any]) -> str:
    names = record.get("corporationNames") or []
    parsed = [n.get("CorporationName") or {} for n in names if isinstance(n, dict)]
    for n in parsed:
        if n.get("current") and str(n.get("nameType", "")).lower() == "primary":
            return str(n.get("name", "")).strip()
    for n in parsed:
        if n.get("current"):
            return str(n.get("name", "")).strip()
    if parsed:
        return str(parsed[0].get("name", "")).strip()
    return ""


def _activity_date(record: dict[str, Any], kinds: tuple[str, ...]) -> date | None:
    wanted = {k.lower() for k in kinds}
    dates: list[date] = []
    for a in record.get("activities") or []:
        act = a.get("activity") if isinstance(a, dict) else None
        if not isinstance(act, dict):
            continue
        if str(act.get("activity", "")).lower() in wanted:
            d = _parse_iso_date(act.get("date"))
            if d:
                dates.append(d)
    return min(dates) if dates else None


def _registered_address(record: dict[str, Any]) -> str | None:
    entries = record.get("adresses") or []
    parsed = [e.get("address") or {} for e in entries if isinstance(e, dict)]
    chosen = next(
        (a for a in parsed if a.get("current") and str(a.get("typeCode")) == "2"), None
    ) or next((a for a in parsed if a.get("current")), None) or (
        parsed[0] if parsed else None
    )
    if not chosen:
        return None
    parts: list[str] = []
    for line in chosen.get("addressLine") or []:
        if line:
            parts.append(str(line).strip())
    for key in ("city", "provinceCode", "postalCode", "countryCode"):
        val = chosen.get(key)
        if val:
            parts.append(str(val).strip())
    return ", ".join(parts) or None


def _is_canadian_filer(submissions: dict[str, Any], forms: list[str]) -> bool:
    """Guard against a US company sharing a Canadian corporation's name."""
    if any(f in _FOREIGN_ISSUER_FORMS for f in forms):
        return True
    addresses = submissions.get("addresses") or {}
    for slot in ("business", "mailing"):
        addr = addresses.get(slot) or {}
        desc = str(addr.get("stateOrCountryDescription") or "").lower()
        if "canada" in desc:
            return True
        if str(addr.get("stateOrCountry") or "").upper() in _CA_STATE_CODES:
            return True
    return False


_CC_RESULT_RE = re.compile(
    r'corpId=(?P<id>\d+)[^"\']*["\'][^>]*>(?P<name>.*?)</a>'
    r'(?P<tail>.*?)(?:Corporation number|Numéro de société|</li>|<a\s)',
    re.IGNORECASE | re.DOTALL,
)
_STATUS_RE = re.compile(r"Status:\s*(?P<status>.*?)</span>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def _parse_cc_results(html_text: str) -> list[tuple[str, str, str | None]]:
    """Pull (corporationId, name, status) tuples from a search result page."""
    out: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for m in _CC_RESULT_RE.finditer(html_text):
        corp_id = m.group("id")
        if corp_id in seen:
            continue
        seen.add(corp_id)
        name = _clean(m.group("name"))
        if not name:
            continue
        status = None
        sm = _STATUS_RE.search(m.group("tail") or "")
        if sm:
            status = _clean(sm.group("status")) or None
        out.append((corp_id, name, status))
    return out


def _parse_iso_date(s: Any) -> date | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _year_of(s: Any) -> int | None:
    d = _parse_iso_date(s)
    return d.year if d else None
