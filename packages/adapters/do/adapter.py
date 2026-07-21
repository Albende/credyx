"""Dominican Republic adapter — DGII (RNC) + BVRD (listed financials).

Sources:
- DGII (Direccion General de Impuestos Internos):
  https://dgii.gov.do/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/rnc.aspx
  The public RNC consultation is an ASP.NET WebForm whose search runs through an
  MS-AJAX UpdatePanel partial postback. Driving that postback (carrying the
  ``__VIEWSTATE`` / ``__EVENTVALIDATION`` tokens) returns the same structured
  record and name-search grid the browser renders. No API key, no CAPTCHA.
- BVRD (Bolsa y Mercados de Valores de la Republica Dominicana):
  https://bvrd.com.do/ — each listed issuer has a public "Estados Financieros"
  downloads page hosting its filed statements as PDFs. The site sits behind
  Cloudflare, so those pages are fetched via the shared FlareSolverr bypass.

Identifier: RNC (Registro Nacional del Contribuyente), 9-11 digits. The classic
corporate RNC is 9 digits; cedula-based RNCs can be 11 digits.
"""
from __future__ import annotations

import html as _html
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.flaresolverr import (
    FlareSolverrError,
    get_flaresolverr_client,
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

_RNC_RE = re.compile(r"^\d{9,11}$")

_DGII_BASE = "https://dgii.gov.do"
_DGII_RNC_PATH = "/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/rnc.aspx"
_DGII_RNC_URL = f"{_DGII_BASE}{_DGII_RNC_PATH}"

_BVRD_BASE = "https://bvrd.com.do"
_BVRD_EMISORES = f"{_BVRD_BASE}/nuestros-emisores/"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_DGII_HEADERS = {"User-Agent": _BROWSER_UA}

_SCRIPT_MANAGER = "ctl00$smMain"
_UPDATE_PANEL = "ctl00$cphMain$upBusqueda"
_BTN_RNC = "ctl00$cphMain$btnBuscarPorRNC"
_BTN_NAME = "ctl00$cphMain$btnBuscarPorRazonSocial"

_MONTHS = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9,
    "septiembr": 9, "sept": 9, "sep": 9, "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
}

_STOPWORDS = {
    "s", "a", "sa", "srl", "s.r.l", "eirl", "de", "del", "la", "el", "los",
    "las", "y", "e", "co", "ltd", "inc", "corp", "banco", "multiple",
    "sociedad", "puesto", "bolsa", "fideicomiso", "oferta", "publica",
    "valores", "no",
}


def _normalize_rnc(value: str) -> str:
    cleaned = re.sub(r"[\s\-\.]", "", value or "")
    if not _RNC_RE.match(cleaned):
        raise InvalidIdentifierError(f"DO RNC must be 9-11 digits, got: {value!r}")
    return cleaned


class DOAdapter(CountryAdapter):
    country_code = "DO"
    country_name = "Dominican Republic"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    DGII_BASE_URL = _DGII_BASE
    BVRD_BASE_URL = _BVRD_BASE

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.DGII_BASE_URL, headers=_DGII_HEADERS
            ) as client:
                resp = await get_with_retry(client, _DGII_RNC_PATH)
                if resp.status_code >= 500:
                    raise RuntimeError(f"DGII returned {resp.status_code}")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=False,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"DGII unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=False,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search/lookup via the DGII RNC consultation WebForm. Financials "
                "via BVRD issuer Estados Financieros pages (listed issuers only)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = (name or "").strip()
        if len(term) < 4:
            raise InvalidIdentifierError(
                "DGII name search requires at least 4 characters."
            )
        try:
            async with build_http_client(
                base_url=self.DGII_BASE_URL, headers=_DGII_HEADERS
            ) as client:
                html = await _dgii_postback(
                    client,
                    event_target=_BTN_NAME,
                    fields={
                        "ctl00$cphMain$txtRNCCedula": "",
                        "ctl00$cphMain$txtRazonSocial": term,
                    },
                )
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"DGII consultation unreachable: {exc!s}"
            ) from exc

        matches: list[CompanyMatch] = []
        for row in _parse_search_grid(html):
            matches.append(
                CompanyMatch(
                    id=row["rnc"],
                    name=row["name"],
                    country=self.country_code,
                    status=row.get("status"),
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT, value=row["rnc"], label="RNC"
                        )
                    ],
                    source_url=_DGII_RNC_URL,
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"DO only supports VAT (RNC) or COMPANY_NUMBER, got {id_type}"
            )
        rnc = _normalize_rnc(value)
        try:
            async with build_http_client(
                base_url=self.DGII_BASE_URL, headers=_DGII_HEADERS
            ) as client:
                html = await _dgii_postback(
                    client,
                    event_target=_BTN_RNC,
                    fields={
                        "ctl00$cphMain$txtRNCCedula": rnc,
                        "ctl00$cphMain$txtRazonSocial": "",
                    },
                )
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"DGII consultation unreachable: {exc!s}"
            ) from exc

        parsed = _parse_detail(html)
        if parsed is None or not parsed.get("name"):
            return None

        return CompanyDetails(
            id=rnc,
            name=parsed["name"],
            country=self.country_code,
            status=parsed.get("status"),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=rnc, label="RNC"),
            ],
            raw=parsed,
            source_url=_DGII_RNC_URL,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        rnc = _normalize_rnc(company_id)

        details = await self.lookup_by_identifier(IdentifierType.VAT, rnc)
        if details is None:
            raise AdapterNotImplementedError(
                f"RNC {rnc} not found in DGII; cannot resolve a BVRD issuer."
            )
        names = [details.name]
        commercial = details.raw.get("commercial_name")
        if commercial:
            names.append(commercial)

        try:
            issuer = await _resolve_bvrd_issuer(names)
        except FlareSolverrError as exc:
            raise AdapterNotImplementedError(
                f"BVRD unreachable (bot wall): {exc!s}"
            ) from exc
        if issuer is None:
            return []

        ef_page = await _find_estados_financieros_page(issuer["profile_url"])
        if ef_page is None:
            return []

        return await _parse_estados_financieros(ef_page, rnc, years)


async def _dgii_postback(
    client: httpx.AsyncClient, *, event_target: str, fields: dict[str, str]
) -> str:
    """Run a DGII consultation UpdatePanel postback and return the response body.

    The consultation form only executes its server-side search on an MS-AJAX
    partial postback, so a fresh GET is needed to lift the anti-forgery tokens
    before POSTing them back with the target button as ``__EVENTTARGET``.
    """
    get_resp = await get_with_retry(client, _DGII_RNC_PATH)
    get_resp.raise_for_status()
    tokens = _extract_tokens(get_resp.text)

    data = {
        _SCRIPT_MANAGER: f"{_UPDATE_PANEL}|{event_target}",
        "__EVENTTARGET": event_target,
        "__EVENTARGUMENT": "",
        "ctl00$cphMain$hidActiveTab": "",
        **fields,
        **tokens,
        "__ASYNCPOST": "true",
    }
    resp = await client.post(
        _DGII_RNC_PATH,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-MicrosoftAjax": "Delta=true",
            "Referer": _DGII_RNC_URL,
        },
    )
    resp.raise_for_status()
    return resp.text


def _extract_tokens(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(
            rf'name="{field}"[^>]*\bvalue="([^"]*)"', html
        ) or re.search(rf'\|hiddenField\|{field}\|([^|]*)\|', html)
        out[field] = m.group(1) if m else ""
    return out


def _slice_region(html: str, start_marker: str, *end_markers: str) -> str | None:
    i = html.find(start_marker)
    if i < 0:
        return None
    end = len(html)
    for marker in end_markers:
        j = html.find(marker, i)
        if 0 <= j < end:
            end = j
    return html[i:end]


def _cells(row_html: str) -> list[str]:
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S | re.I)
    return [_clean(c) or "" for c in cells]


def _parse_detail(html: str) -> dict[str, Any] | None:
    region = _slice_region(
        html, "dvDatosContribuyentes", "|0|hiddenField|__EVENTTARGET"
    )
    if region is None:
        return None

    values: dict[str, str] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", region, re.S | re.I):
        cells = [c for c in _cells(row) if c]
        if len(cells) >= 2:
            values[cells[0].lower()] = cells[1]

    def pick(*needles: str) -> str | None:
        for key, val in values.items():
            if any(n in key for n in needles):
                return val or None
        return None

    name = pick("nombre/raz", "raz")
    if not name:
        return None
    return {
        "name": name,
        "commercial_name": pick("nombre comercial"),
        "status": pick("estado"),
        "activity": pick("actividad econ"),
        "payment_regime": pick("gimen de pago"),
        "category": pick("categor"),
        "local_office": pick("administracion local", "administraci"),
        "e_invoicing": pick("facturador"),
    }


def _parse_search_grid(html: str) -> list[dict[str, str]]:
    region = _slice_region(html, 'id="cphMain_gvBuscRazonSocial"', "</table>")
    if region is None:
        return []
    rows: list[dict[str, str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", region, re.S | re.I):
        cells = _cells(row)
        if len(cells) < 6:
            continue
        rnc = re.sub(r"\D", "", cells[0])
        if not rnc:
            continue
        rows.append(
            {
                "rnc": rnc,
                "name": cells[1],
                "commercial_name": cells[2],
                "status": cells[5],
            }
        )
    return rows


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = _html.unescape(_TAG_RE.sub(" ", value))
    stripped = _WS_RE.sub(" ", stripped).replace("\xa0", " ").strip()
    return stripped or None


def _norm_tokens(name: str) -> set[str]:
    text = _html.unescape(name).lower()
    text = (
        text.replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )
    tokens = re.findall(r"[a-z0-9]+", text)
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


async def _bvrd_fetch(url: str) -> tuple[str, list[dict], str]:
    flare = get_flaresolverr_client()
    resp = await flare.fetch_html(url)
    return resp.html, resp.cookies, resp.user_agent


async def _resolve_bvrd_issuer(names: list[str]) -> dict[str, str] | None:
    html, _, _ = await _bvrd_fetch(_BVRD_EMISORES)
    issuers: list[tuple[str, str, set[str]]] = []
    seen: set[str] = set()
    skip = re.compile(
        r"nuestros-emisores|quienes-somos|indices|contacto|noticias|marco|"
        r"producto|servicio|pregunta|glosario|educacion|home|inicio|blog|"
        r"prensa|category|wp-|feed|politica|termino|mercado|puesto|regulacion|"
        r"estadistica|transparencia|intermediar|inversionista|normativa|"
        r"renta-variable|boletin|horario|remix|fimva|downloads|^emisores$",
        re.I,
    )
    for slug, txt in re.findall(
        r'<a\s[^>]*href="https://bvrd\.com\.do/([a-z0-9-]+)/"[^>]*>(.*?)</a>',
        html,
        re.S | re.I,
    ):
        label = _clean(txt)
        if not label or len(label) < 4 or slug in seen or skip.search(slug):
            continue
        seen.add(slug)
        issuers.append((slug, label, _norm_tokens(label)))

    query_tokens: set[str] = set()
    for n in names:
        query_tokens |= _norm_tokens(n)
    if not query_tokens:
        return None

    best: tuple[float, str, str] | None = None
    for slug, label, toks in issuers:
        if not toks:
            continue
        overlap = len(query_tokens & toks)
        if overlap == 0:
            continue
        score = overlap / len(toks)
        if score >= 0.6 and (best is None or score > best[0]):
            best = (score, slug, label)
    if best is None:
        return None
    return {
        "profile_url": f"{_BVRD_BASE}/{best[1]}/",
        "name": best[2],
        "slug": best[1],
    }


async def _find_estados_financieros_page(profile_url: str) -> str | None:
    html, _, _ = await _bvrd_fetch(profile_url)
    candidates: list[tuple[str, str]] = []
    for url, txt in re.findall(
        r'<a\s[^>]*href="(https://bvrd\.com\.do/downloads/[^"]+)"[^>]*>(.*?)</a>',
        html,
        re.S | re.I,
    ):
        label = (_clean(txt) or "").lower()
        candidates.append((_html.unescape(url), label))
    for url, label in candidates:
        if "estado" in label and "financ" in label:
            return url
    for url, label in candidates:
        if "financ" in label or "eeff" in url.lower():
            return url
    return None


async def _parse_estados_financieros(
    ef_url: str, rnc: str, years: int
) -> list[FinancialFiling]:
    html, cookies, user_agent = await _bvrd_fetch(ef_url)

    seen: set[str] = set()
    raw_filings: list[tuple[str, str, int, date | None, FilingType]] = []
    for m in re.finditer(
        r'href="(https://bvrd\.com\.do/downloads/[^"]*?'
        r'filename=([^&"]+\.pdf)[^"]*)"',
        html,
        re.I,
    ):
        doc_url = _html.unescape(m.group(1))
        filename = _html.unescape(m.group(2))
        if filename in seen:
            continue
        seen.add(filename)

        year, period_end = _extract_period(filename, doc_url)
        if year is None:
            continue
        raw_filings.append(
            (doc_url, filename, year, period_end, _classify(filename))
        )

    if not raw_filings:
        return []
    raw_filings.sort(key=lambda r: r[2], reverse=True)
    cutoff = raw_filings[0][2] - years + 1
    raw_filings = [r for r in raw_filings if r[2] >= cutoff]

    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    filings: list[FinancialFiling] = []
    async with build_http_client(
        headers={"User-Agent": user_agent, "Cookie": cookie_header}
    ) as client:
        for doc_url, filename, year, period_end, ftype in raw_filings:
            document_url = (
                doc_url if await _downloads_pdf(client, doc_url) else None
            )
            filings.append(
                FinancialFiling(
                    company_id=rnc,
                    year=year,
                    type=ftype,
                    period_end=period_end,
                    document_url=document_url,
                    document_format="pdf" if document_url else None,
                    source_url=ef_url,
                    structured_data={"filename": filename},
                )
            )
    return filings


async def _downloads_pdf(client: httpx.AsyncClient, url: str) -> bool:
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                return False
            ctype = resp.headers.get("content-type", "").lower()
            return "pdf" in ctype or "octet-stream" in ctype
    except httpx.HTTPError:
        return False


def _extract_period(filename: str, doc_url: str) -> tuple[int | None, date | None]:
    text = filename.lower()
    month = None
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\b", text):
            month = num
            break
    year_match = re.search(r"\b(19|20)\d{2}\b", filename)
    if year_match:
        year = int(year_match.group(0))
        period_end = _month_end(year, month) if month else None
        return year, period_end

    ind = re.search(r"[?&]ind=(\d{10,})", doc_url)
    if ind:
        published = datetime.utcfromtimestamp(int(ind.group(1)) / 1000)
        return published.year, None
    return None, None


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    first_next = date(year + (month // 12), (month % 12) + 1, 1)
    return date.fromordinal(first_next.toordinal() - 1)


def _classify(filename: str) -> FilingType:
    text = filename.lower()
    if "balance" in text:
        return FilingType.BALANCE_SHEET
    if "resultado" in text:
        return FilingType.PROFIT_AND_LOSS
    if "flujo" in text and "efectivo" in text:
        return FilingType.CASH_FLOW
    if "auditad" in text or "auditoria" in text:
        return FilingType.AUDIT_REPORT
    return FilingType.ANNUAL_REPORT
