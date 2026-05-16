"""Bosnia and Herzegovina adapter.

The BiH commercial registry is fragmented across three jurisdictions:

* Federation of BiH — https://bizreg.pravosudje.ba/  (primary, default)
* Republika Srpska   — https://bizreg.esrpska.com/   (fallback)
* Brčko District     — separate portal, not searched here

All three expose free, no-auth, public HTML search pages. There is no
official JSON API: this adapter posts the same form a browser would submit
and parses the resulting result table. Annual filings for listed firms are
published as free PDFs on the Sarajevo Stock Exchange (SASE) and Banja Luka
Stock Exchange (BLSE); they are not centrally indexed, so `fetch_financials`
returns the per-issuer listing URL as a discovery pointer rather than
synthesizing numbers.

Identifiers:
  JIB — Jedinstveni Identifikacijski Broj, 13 digits (tax-style ID)
  MB  — Matični broj, 7-13 digits (company registration number)
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_JIB_RE = re.compile(r"^\d{13}$")
_MB_RE = re.compile(r"^\d{7,13}$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_LISTED_SASE = {
    "4200211100005": "BHTSR",   # BH Telecom
    "4200225150005": "JPESR",   # JP Elektroprivreda BiH
    "4200119190100": "BSNLR",   # Bosnalijek
}


def _normalize_jib(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _JIB_RE.match(cleaned):
        raise InvalidIdentifierError(f"BA JIB must be exactly 13 digits: {value}")
    return cleaned


def _normalize_mb(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _MB_RE.match(cleaned):
        raise InvalidIdentifierError(f"BA MB must be 7-13 digits: {value}")
    return cleaned


def _strip_html(fragment: str) -> str:
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", fragment))).strip()


class BAAdapter(CountryAdapter):
    country_code = "BA"
    country_name = "Bosnia and Herzegovina"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    FBIH_BASE = "https://bizreg.pravosudje.ba"
    RS_BASE = "https://bizreg.esrpska.com"
    SASE_BASE = "https://www.sase.ba"
    BLSE_BASE = "https://www.blberza.com"

    def _client(self, base_url: str) -> httpx.AsyncClient:
        # BiH registries occasionally serve windows-1250 / iso-8859-2; httpx
        # auto-decodes via the Content-Type header. We just send a permissive
        # Accept and let upstream choose.
        return build_http_client(
            base_url=base_url,
            timeout=30.0,
            headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"},
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client(self.FBIH_BASE) as client:
                resp = await get_with_retry(client, "/")
                if resp.status_code >= 500:
                    raise AdapterError(f"FBiH bizreg HTTP {resp.status_code}")
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
            status=AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Fragmented HTML registries (FBiH/RS/Brcko). Structured "
                "filings only for SASE/BLSE-listed issuers as PDFs."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        matches: list[CompanyMatch] = []
        # Federation first (covers ~63% of the country).
        matches.extend(await self._search_fbih(name, limit))
        if len(matches) < limit:
            matches.extend(await self._search_rs(name, limit - len(matches)))
        # De-duplicate by JIB / MB / name.
        seen: set[str] = set()
        deduped: list[CompanyMatch] = []
        for m in matches:
            key = m.id or m.name.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(m)
        return deduped[:limit]

    async def _search_fbih(self, name: str, limit: int) -> list[CompanyMatch]:
        # FBiH bizreg uses a public search form posting `naziv` (name). The
        # response is an HTML table where each row contains JIB, MB, naziv,
        # sjedište (seat) and a court reference.
        params = {"naziv": name, "limit": str(limit)}
        try:
            async with self._client(self.FBIH_BASE) as client:
                resp = await client.get("/pretraga/subjekti", params=params)
                if resp.status_code != 200:
                    return []
                html = resp.text
        except httpx.HTTPError:
            return []
        return _parse_search_table(
            html=html,
            country_code=self.country_code,
            source_url=f"{self.FBIH_BASE}/pretraga/subjekti?naziv={name}",
            jurisdiction="FBiH",
            limit=limit,
        )

    async def _search_rs(self, name: str, limit: int) -> list[CompanyMatch]:
        params = {"naziv": name, "limit": str(limit)}
        try:
            async with self._client(self.RS_BASE) as client:
                resp = await client.get("/pretraga/subjekti", params=params)
                if resp.status_code != 200:
                    return []
                html = resp.text
        except httpx.HTTPError:
            return []
        return _parse_search_table(
            html=html,
            country_code=self.country_code,
            source_url=f"{self.RS_BASE}/pretraga/subjekti?naziv={name}",
            jurisdiction="RS",
            limit=limit,
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            normalized = _normalize_jib(value)
            param = "jib"
        elif id_type == IdentifierType.COMPANY_NUMBER:
            normalized = _normalize_mb(value)
            param = "mb"
        else:
            raise InvalidIdentifierError(
                f"BA supports VAT (JIB) and COMPANY_NUMBER (MB), got {id_type}"
            )

        details = await self._lookup_at(self.FBIH_BASE, param, normalized, "FBiH")
        if details is None:
            details = await self._lookup_at(self.RS_BASE, param, normalized, "RS")
        return details

    async def _lookup_at(
        self, base: str, param: str, value: str, jurisdiction: str
    ) -> CompanyDetails | None:
        try:
            async with self._client(base) as client:
                resp = await get_with_retry(
                    client, f"/subjekt?{param}={value}",
                )
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    return None
                html = resp.text
        except httpx.HTTPError:
            return None

        fields = _parse_detail_fields(html)
        if not fields.get("naziv") and not fields.get("name"):
            return None
        jib = fields.get("jib") or (value if param == "jib" else "")
        mb = fields.get("mb") or (value if param == "mb" else "")
        identifiers: list[RegistryIdentifier] = []
        if jib:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.VAT, value=jib, label="JIB")
            )
        if mb:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=mb, label="MB"
                )
            )
        company_id = jib or mb
        return CompanyDetails(
            id=company_id,
            name=fields.get("naziv") or fields.get("name") or "",
            country=self.country_code,
            legal_form=fields.get("pravna_forma") or fields.get("oblik"),
            status=fields.get("status"),
            incorporation_date=_parse_ba_date(fields.get("datum_osnivanja")),
            dissolution_date=_parse_ba_date(fields.get("datum_brisanja")),
            registered_address=fields.get("sjediste") or fields.get("adresa"),
            capital_amount=_parse_amount(fields.get("kapital")),
            capital_currency="BAM" if fields.get("kapital") else None,
            identifiers=identifiers,
            raw={"jurisdiction": jurisdiction, "fields": fields},
            source_url=f"{base}/subjekt?{param}={value}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Only SASE-listed issuers have structured public annual reports
        # under our free-source rule. For everyone else, BiH filings live
        # behind paid registry portals or in court archives — return [].
        try:
            jib = _normalize_jib(company_id)
        except InvalidIdentifierError:
            return []

        if jib not in _LISTED_SASE:
            return []

        ticker = _LISTED_SASE[jib]
        # SASE publishes per-issuer financial-report listings at a stable
        # URL pattern. We return a single discovery pointer per recent year;
        # PDF parsing is a Phase-2 task.
        current_year = datetime.utcnow().year
        listing_url = f"{self.SASE_BASE}/v1/Emitent/Index/{ticker}"
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - offset - 1
            filings.append(
                FinancialFiling(
                    company_id=jib,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="BAM",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=listing_url,
                )
            )
        return filings


def _parse_search_table(
    *,
    html: str,
    country_code: str,
    source_url: str,
    jurisdiction: str,
    limit: int,
) -> list[CompanyMatch]:
    matches: list[CompanyMatch] = []
    for row_html in _ROW_RE.findall(html):
        cells = [_strip_html(c) for c in _CELL_RE.findall(row_html)]
        if len(cells) < 2:
            continue
        # Heuristic: pick out a 13-digit JIB and an MB anywhere in the row.
        jib = next((c for c in cells if _JIB_RE.match(c)), "")
        mb_candidates = [c for c in cells if _MB_RE.match(c) and c != jib]
        mb = mb_candidates[0] if mb_candidates else ""
        # Company name is the longest non-numeric cell.
        name_cells = [c for c in cells if c and not c.replace(" ", "").isdigit()]
        if not name_cells:
            continue
        company_name = max(name_cells, key=len)
        if not jib and not mb:
            continue
        identifiers: list[RegistryIdentifier] = []
        if jib:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.VAT, value=jib, label="JIB")
            )
        if mb:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=mb, label="MB"
                )
            )
        matches.append(
            CompanyMatch(
                id=jib or mb,
                name=company_name,
                country=country_code,
                identifiers=identifiers,
                address=next(
                    (c for c in name_cells if c != company_name and len(c) > 4),
                    None,
                ),
                status=jurisdiction,
                source_url=source_url,
            )
        )
        if len(matches) >= limit:
            break
    return matches


# Lines in the detail page render as "Label: value". This catches both
# table-cell labels and prose. Keep keys ASCII-lowercase so the call sites
# stay readable.
_LABEL_MAP: dict[str, str] = {
    "naziv": "naziv",
    "naziv subjekta": "naziv",
    "puni naziv": "naziv",
    "skraceni naziv": "skraceni_naziv",
    "skraćeni naziv": "skraceni_naziv",
    "jib": "jib",
    "matični broj": "mb",
    "maticni broj": "mb",
    "pravni oblik": "pravna_forma",
    "oblik organiziranja": "oblik",
    "sjedište": "sjediste",
    "sjediste": "sjediste",
    "adresa": "adresa",
    "datum osnivanja": "datum_osnivanja",
    "datum upisa": "datum_osnivanja",
    "datum brisanja": "datum_brisanja",
    "status": "status",
    "osnovni kapital": "kapital",
    "kapital": "kapital",
    "djelatnost": "djelatnost",
}

_LABEL_LINE_RE = re.compile(
    r"([A-Za-zČĆŽŠĐčćžšđ\u0400-\u04FF ]{3,40})\s*[:：]\s*([^\n<]{1,300})"
)


def _parse_detail_fields(html: str) -> dict[str, str]:
    text = _strip_html(html)
    out: dict[str, str] = {}
    for label, value in _LABEL_LINE_RE.findall(text):
        key = label.strip().lower()
        norm = _LABEL_MAP.get(key)
        if norm and norm not in out:
            out[norm] = value.strip()
    return out


def _parse_ba_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    # BiH writes dates as 31.12.2023 or 31.12.2023.; ISO is rare here.
    for sep in (".", "/", "-"):
        if sep in value:
            parts = [p for p in value.split(sep) if p]
            if len(parts) >= 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2][:4])
                    return date(y, m, d)
                except ValueError:
                    continue
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9,\.]", "", value).replace(".", "").replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None
