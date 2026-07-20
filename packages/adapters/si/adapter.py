"""Slovenia adapter — AJPES registry + Ljubljana Stock Exchange filings.

Identifier / registry sources (AJPES — Agencija RS za javnopravne evidence
in storitve):
- eObjave (court-register publications): https://www.ajpes.si/eObjave/
  Public, no auth. Returns name + matična številka (registration number) +
  davčna številka (tax/VAT) for each filing. Used as the canonical identifier
  source because it exposes both IDs together in plain HTML rows.
- JOLP (Javna objava letnih poročil): https://www.ajpes.si/jolp/
  Public name/identifier search returns address + postcode + city. Used to
  enrich the registered address. The individual annual-report PDFs on JOLP
  require an AJPES free-but-registered login, so they are not the financials
  source here.

Financial-statement source (SEOnet — the Ljubljana Stock Exchange official
disclosure portal): https://seonet.ljse.si/
  Public, no auth. Listed issuers publish their audited annual reports and
  semi-annual/interim reports here, most as ESEF (European Single Electronic
  Format) iXBRL packages plus PDFs. The English endpoint exposes a
  brand-first issuer directory and an "annual & semi-annual reports" view
  filterable by issuer + publication year. Registry matičnas carry no SEOnet
  cross-walk, so an issuer is matched by its brand token against the AJPES
  company name. Companies that are not listed on the exchange have no public
  filings (private-company accounts sit behind the AJPES session), so
  fetch_financials raises AdapterNotImplementedError for them.

Approach: HTML scraping with stdlib re only (no bs4/lxml dependency).
Defensive parsing — if a layout change breaks a row we skip it rather than
crash.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote_plus

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

_MATICNA_RE = re.compile(r"^\d{10}$")
_DAVCNA_RE = re.compile(r"^\d{8}$")

# eObjave result rows: each <tr> has 6 <td> cells, several of which wrap an
# `<a href="objava.asp?s=...&id=N">VALUE</a>` link with the field value. We
# extract the row block then pull the named anchor groups.
_ROW_BLOCK_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_BLOCK_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_ANCHOR_TEXT_RE = re.compile(r">\s*([^<]+?)\s*<", re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

# JOLP result row column order: name (link), address, postcode, city, court,
# vlozna številka.
_JOLP_ROW_RE = re.compile(
    r'<a\s+href="podjetje\.asp\?maticna=(?P<mat>\d{10})">\s*'
    r"(?P<name>[^<]+?)\s*</a>"
    r"(?P<rest>.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)

# SEOnet fast-search issuer dropdown: <option value="434">KRKA, d. d., ...
_SEONET_ISSUER_SELECT_RE = re.compile(
    r'name="fast_search_issuer".*?</select>', re.IGNORECASE | re.DOTALL
)
_SEONET_OPTION_RE = re.compile(
    r'<option\s+value="(\d+)"[^>]*>([^<]+)', re.IGNORECASE
)
# SEOnet result rows: a go_to(...doc_id=N) anchor whose enclosing <tr> holds
# the publication date and the announcement title in <td> cells.
_SEONET_ROW_RE = re.compile(
    r"go_to\(null,\s*'[^']*doc_id=(\d+)'\)[^>]*>(.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)
_SEONET_ATTACH_RE = re.compile(
    r"file\.aspx\?AttachmentID=(\d+)", re.IGNORECASE
)
_CD_FILENAME_STAR_RE = re.compile(
    r"filename\*=(?:UTF-8'')?([^;\r\n]+)", re.IGNORECASE
)
_CD_FILENAME_RE = re.compile(r'filename="([^"]+)"', re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"(19|20)\d{2}-\d{2}-\d{2}")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_TOKEN_RE = re.compile(r"[0-9A-Za-zČŠŽĆĐčšžćđ]+")

# Legal-form / generic tokens that never identify a specific company.
_STOP_TOKENS = frozenset(
    {
        "DD", "DOO", "ZOO", "SP", "KD", "GIZ", "KDD", "DNO",
        "D", "O", "Z", "IN", "THE",
    }
)


def _normalize_maticna(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if not _MATICNA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"SI Matična številka must be 10 digits, got: {value}"
        )
    return cleaned


def _normalize_davcna(value: str) -> str:
    cleaned = value.strip().replace(" ", "").upper()
    if cleaned.startswith("SI"):
        cleaned = cleaned[2:]
    if not _DAVCNA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"SI Davčna številka (VAT) must be 8 digits, got: {value}"
        )
    return cleaned


def _strip(text: str) -> str:
    return html.unescape(_TAG_STRIP_RE.sub("", text)).strip()


class SIAdapter(CountryAdapter):
    country_code = "SI"
    country_name = "Slovenia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    EOB_BASE = "https://www.ajpes.si/eObjave"
    JOLP_BASE = "https://www.ajpes.si/jolp"
    # id_skupina=48 = court-register publication index (splošni vpis), the
    # broadest public stream covering every active SI business subject.
    EOB_GROUP = 48

    SEONET_BASE = "https://seonet.ljse.si"
    # The "annual & semi-annual reports" view; combined in one POST with the
    # fast-search issuer filter and a publication-year filter it returns a
    # listed company's filed reports for that year.
    SEONET_REPORTS_DOC = "ANNUAL_AND_SEMI_ANNUAL_REPORTS"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.EOB_BASE) as client:
                resp = await get_with_retry(client, "/default.asp", params={"s": self.EOB_GROUP})
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "AJPES eObjave + JOLP public scrape for registry data; "
                "Ljubljana Stock Exchange SEOnet for listed-issuer filings. "
                "Private-company accounts (AJPES session) are out of scope."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._eobjave_search(firma=name)
        seen: set[str] = set()
        matches: list[CompanyMatch] = []
        for row in rows:
            mat = row.get("maticna")
            if not mat or mat in seen:
                continue
            seen.add(mat)
            vat = row.get("davcna")
            idents = [
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=mat,
                    label="Matična številka",
                )
            ]
            if vat:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=f"SI{vat}",
                        label="Davčna številka",
                    )
                )
            matches.append(
                CompanyMatch(
                    id=mat,
                    name=row.get("firma", ""),
                    country=self.country_code,
                    identifiers=idents,
                    address=None,
                    status=None,
                    source_url=self._eobjave_link_for(mat),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            params: dict[str, Any] = {"Maticna": _normalize_maticna(value)}
        elif id_type == IdentifierType.VAT:
            params = {"Davcna": _normalize_davcna(value)}
        else:
            raise InvalidIdentifierError(
                f"SI only supports COMPANY_NUMBER (Matična) or VAT (Davčna), got {id_type}"
            )

        rows = await self._eobjave_search(**params)
        if not rows:
            return None

        first = rows[0]
        mat = first.get("maticna") or ""
        vat = first.get("davcna")
        firma = first.get("firma", "")
        if not mat:
            return None

        address = await self._jolp_address_for(mat)

        idents = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=mat,
                label="Matična številka",
            )
        ]
        if vat:
            idents.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=f"SI{vat}",
                    label="Davčna številka",
                )
            )

        return CompanyDetails(
            id=mat,
            name=firma,
            country=self.country_code,
            legal_form=None,
            status=None,
            registered_address=address,
            capital_currency="EUR",
            identifiers=idents,
            raw={"eobjave_first_row": first, "jolp_address": address},
            source_url=self._eobjave_link_for(mat),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        maticna = _normalize_maticna(company_id)

        rows = await self._eobjave_search(Maticna=maticna)
        name = rows[0].get("firma") if rows else None
        if not name:
            raise AdapterNotImplementedError(
                f"SI matična {maticna} not found in AJPES eObjave; cannot "
                "resolve the company to a Ljubljana Stock Exchange issuer."
            )

        issuer = await self._seonet_issuer_for(name)
        if issuer is None:
            raise AdapterNotImplementedError(
                f"'{name}' is not a Ljubljana Stock Exchange (SEOnet) issuer. "
                "Public filed financials in SI are available only for listed "
                "companies; private-company accounts sit behind the AJPES "
                "registered session — see docs/countries/si.md."
            )

        issuer_id, _issuer_name = issuer
        filings = await self._seonet_filings(issuer_id, maticna, years)
        if not filings:
            raise AdapterNotImplementedError(
                f"'{name}' (SEOnet issuer {issuer_id}) has no annual or "
                "semi-annual reports published on SEOnet for the requested "
                "period."
            )
        return filings

    def _eobjave_link_for(self, maticna: str) -> str:
        return (
            f"{self.EOB_BASE}/rezultati.asp?"
            f"podrobno=0&id_skupina={self.EOB_GROUP}&Maticna={maticna}"
        )

    async def _eobjave_search(self, **params: Any) -> list[dict[str, str]]:
        q = {"podrobno": "0", "id_skupina": str(self.EOB_GROUP)}
        for k, v in params.items():
            if v is None:
                continue
            q[k] = str(v)
        async with build_http_client(base_url=self.EOB_BASE) as client:
            resp = await get_with_retry(client, "/rezultati.asp", params=q)
            resp.raise_for_status()
            return _parse_eobjave_rows(resp.text)

    async def _jolp_address_for(self, maticna: str) -> str | None:
        url = f"/rezultati.asp?maticna={quote_plus(maticna)}&podrobno=0"
        async with build_http_client(base_url=self.JOLP_BASE) as client:
            resp = await get_with_retry(client, url)
            if resp.status_code != 200:
                return None
            return _parse_jolp_address(resp.text, maticna)

    def _seonet_client(self) -> Any:
        return build_http_client(
            base_url=self.SEONET_BASE,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36 Credyx/0.1"
                )
            },
        )

    async def _seonet_issuer_for(self, name: str) -> tuple[str, str] | None:
        async with self._seonet_client() as client:
            resp = await get_with_retry(
                client, "/default_en.aspx", params={"doc": "LATEST_PUBLIC_ANNOUNCEMENTS"}
            )
            resp.raise_for_status()
            issuers = _parse_seonet_issuers(resp.text)
        return _match_issuer(name, issuers)

    async def _seonet_filings(
        self, issuer_id: str, maticna: str, years: int
    ) -> list[FinancialFiling]:
        current = datetime.utcnow().year
        wanted = max(years, 1)
        seen_docs: set[str] = set()
        filings: list[FinancialFiling] = []
        async with self._seonet_client() as client:
            for pub_year in range(current, current - wanted - 1, -1):
                if len(filings) >= wanted:
                    break
                rows = await self._seonet_reports_for_year(client, issuer_id, pub_year)
                for doc_id, title, pub_date in rows:
                    if doc_id in seen_docs:
                        continue
                    seen_docs.add(doc_id)
                    filing = await self._seonet_filing_from_doc(
                        client, doc_id, title, pub_date, maticna
                    )
                    if filing is not None:
                        filings.append(filing)
                    if len(filings) >= wanted:
                        break
        return filings

    async def _seonet_reports_for_year(
        self, client: Any, issuer_id: str, pub_year: int
    ) -> list[tuple[str, str, date | None]]:
        data = {
            "doc": self.SEONET_REPORTS_DOC,
            "fast_search_issuer": issuer_id,
            "fast_search_submition": "true",
            "fast_search_submit_button": "Search",
            "fast_search_words": "",
            "fast_search_date_from": "",
            "fast_search_date_to": "",
            "FSs_date_range": "",
            "field.selected_year": str(pub_year),
            "field.page_no": "1",
        }
        resp = await client.post("/default_en.aspx", data=data)
        resp.raise_for_status()
        return _parse_seonet_report_rows(resp.text)

    async def _seonet_filing_from_doc(
        self,
        client: Any,
        doc_id: str,
        title: str,
        pub_date: date | None,
        maticna: str,
    ) -> FinancialFiling | None:
        resp = await client.get("/", params={"doc_id": doc_id})
        if resp.status_code != 200:
            return None
        attachment_id = _first_attachment_id(resp.text)
        source_url = f"{self.SEONET_BASE}/?doc_id={doc_id}"
        if attachment_id is None:
            return None

        document_url = None
        document_format = None
        filename = None
        async with client.stream(
            "GET", "/file.aspx", params={"AttachmentID": attachment_id}
        ) as att:
            if att.status_code == 200:
                document_url = f"{self.SEONET_BASE}/file.aspx?AttachmentID={attachment_id}"
                filename = _content_disposition_filename(
                    att.headers.get("content-disposition", "")
                )
                document_format = _document_format(
                    filename, att.headers.get("content-type", "")
                )

        fiscal_year, period_end = _fiscal_year_from(filename, title, pub_date)
        return FinancialFiling(
            company_id=maticna,
            year=fiscal_year,
            type=FilingType.ANNUAL_REPORT,
            period_end=period_end,
            currency="EUR",
            document_url=document_url,
            document_format=document_format,
            source_url=source_url,
        )


def _parse_eobjave_rows(html_text: str) -> list[dict[str, str]]:
    """Extract rows from an eObjave rezultati.asp results table.

    Each row's six <td> cells are: datum objave, vrsta, firma, matična,
    davčna, srg številka. Several cells wrap the value inside an anchor —
    we strip tags + entities to get the plain text.
    """
    # Slice to the results <tbody> if present; otherwise scan the whole page.
    body_start = html_text.lower().find("<tbody>")
    body_end = html_text.lower().find("</tbody>", body_start + 1)
    region = (
        html_text[body_start:body_end] if body_start != -1 and body_end != -1 else html_text
    )
    out: list[dict[str, str]] = []
    for row_match in _ROW_BLOCK_RE.finditer(region):
        cells = _TD_BLOCK_RE.findall(row_match.group(1))
        if len(cells) < 6:
            continue
        date_s = _strip(cells[0])
        vrsta = _strip(cells[1])
        firma = _strip(cells[2])
        maticna = _strip(cells[3])
        davcna = _strip(cells[4])
        srg = _strip(cells[5])
        if not _MATICNA_RE.match(maticna):
            continue
        out.append(
            {
                "datum": date_s,
                "vrsta": vrsta,
                "firma": firma,
                "maticna": maticna,
                "davcna": davcna if _DAVCNA_RE.match(davcna) else "",
                "srg": srg,
            }
        )
    return out


def _parse_jolp_address(html_text: str, maticna: str) -> str | None:
    """Pull the (street, postcode, city) of the matching JOLP result row.

    JOLP result rows look like:
        <a href="podjetje.asp?maticna=NNNN">NAME</a></td>
        <td valign="top">Šmarješka cesta 6 </td>
        <td valign="top">8000</td>
        <td valign="top">Novo mesto</td>
    Returns "<street>, <postcode> <city>" or None if not found.
    """
    for m in _JOLP_ROW_RE.finditer(html_text):
        if m.group("mat") != maticna:
            continue
        rest = m.group("rest")
        cells = _TD_BLOCK_RE.findall(rest)
        if len(cells) < 3:
            return None
        street = _strip(cells[0])
        postcode = _strip(cells[1])
        city = _strip(cells[2])
        parts = [p for p in [street, f"{postcode} {city}".strip()] if p]
        return ", ".join(parts) or None
    return None


def _coerce_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _tokens(text: str) -> list[str]:
    return [t.upper() for t in _TOKEN_RE.findall(text)]


def _significant_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if len(t) >= 2 and t not in _STOP_TOKENS}


def _parse_seonet_issuers(html_text: str) -> list[tuple[str, str]]:
    select = _SEONET_ISSUER_SELECT_RE.search(html_text)
    if not select:
        return []
    out: list[tuple[str, str]] = []
    for value, label in _SEONET_OPTION_RE.findall(select.group(0)):
        name = html.unescape(label).strip()
        if name:
            out.append((value, name))
    return out


def _match_issuer(
    company_name: str, issuers: list[tuple[str, str]]
) -> tuple[str, str] | None:
    """Map an AJPES company name to a SEOnet issuer.

    Both AJPES and SEOnet name a listed company brand-first (AJPES:
    ``KRKA, tovarna zdravil, d.d., Novo mesto``; SEOnet: ``KRKA, d. d., Novo
    mesto``), so a match requires the two leading brand tokens to be equal
    *and* one name's significant tokens to be a subset of the other's. The
    subset guard is what stops two unrelated firms that merely share a generic
    lead word (``PEKARNA BLATNIK`` vs ``PEKARNA CENTER LOGATEC``) from binding.
    Remaining ties favour the tighter overlap, the shorter issuer name, then
    the lower (older, primary) issuer id.
    """
    company_brand = next(
        (t for t in _tokens(company_name) if t not in _STOP_TOKENS), None
    )
    if company_brand is None or len(company_brand) < 3:
        return None
    company_tokens = _significant_tokens(company_name)
    best: tuple[int, int, int, str] | None = None
    best_match: tuple[str, str] | None = None
    for value, issuer_name in issuers:
        issuer_tokens = _significant_tokens(issuer_name)
        brand = next(
            (t for t in _tokens(issuer_name) if t not in _STOP_TOKENS), None
        )
        if brand != company_brand:
            continue
        if not (
            issuer_tokens <= company_tokens or company_tokens <= issuer_tokens
        ):
            continue
        overlap = len(company_tokens & issuer_tokens)
        key = (overlap, -len(_tokens(issuer_name)), -int(value), issuer_name)
        if best is None or key > best:
            best = key
            best_match = (value, issuer_name)
    return best_match


def _parse_seonet_report_rows(
    html_text: str,
) -> list[tuple[str, str, date | None]]:
    out: list[tuple[str, str, date | None]] = []
    for doc_id, row in _SEONET_ROW_RE.findall(html_text):
        cells = [_strip(c) for c in _TD_BLOCK_RE.findall(row)]
        cells = [c for c in cells if c]
        title = cells[-1] if cells else ""
        pub_date = next(
            (_coerce_us_date(c) for c in cells if _coerce_us_date(c)), None
        )
        out.append((doc_id, title, pub_date))
    return out


def _coerce_us_date(s: str) -> date | None:
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _first_attachment_id(html_text: str) -> str | None:
    m = _SEONET_ATTACH_RE.search(html_text)
    return m.group(1) if m else None


def _content_disposition_filename(header: str) -> str | None:
    m = _CD_FILENAME_STAR_RE.search(header)
    if m:
        from urllib.parse import unquote

        return unquote(m.group(1)).strip()
    m = _CD_FILENAME_RE.search(header)
    return m.group(1).strip() if m else None


def _document_format(filename: str | None, content_type: str) -> str | None:
    name = (filename or "").lower()
    if name.endswith(".zip") or name.endswith(".xhtml"):
        return "xbrl"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".htm", ".html")):
        return "html"
    ctype = content_type.lower()
    if "pdf" in ctype:
        return "pdf"
    if "zip" in ctype:
        return "xbrl"
    if "html" in ctype:
        return "html"
    return None


def _fiscal_year_from(
    filename: str | None, title: str, pub_date: date | None
) -> tuple[int, date | None]:
    """Derive the fiscal year (and period end where stated) of a report.

    ESEF packages are named ``<LEI>-YYYY-MM-DD-...zip``, which pins both. Other
    filings carry the period year in the filename or title. Absent any of
    those, an audited annual report is filed the year after its period, so the
    publication year minus one is the closest honest fallback.
    """
    for text in (filename, title):
        if not text:
            continue
        iso = _ISO_DATE_RE.search(text)
        if iso:
            end = _coerce_date(iso.group(0))
            if end:
                return end.year, end
    for text in (filename, title):
        if not text:
            continue
        year = _YEAR_RE.search(text)
        if year:
            return int(year.group(0)), None
    if pub_date:
        lowered = title.lower()
        if "annual" in lowered:
            return pub_date.year - 1, None
        return pub_date.year, None
    return datetime.utcnow().year, None
