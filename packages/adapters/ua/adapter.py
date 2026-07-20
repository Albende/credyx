"""Ukraine adapter — Clarity Project (open data mirror of YeDR).

The official YeDR (Yedyny derzhavnyy reyestr pidpryyemstv ta orhanizatsiy
Ukrayiny) is published as XML/JSON dumps on data.gov.ua and as a captcha-
protected HTML form at https://usr.minjust.gov.ua. Neither is a queryable
live API. Clarity Project re-publishes the same open data; its former
unauthenticated JSON API (`/api/search`, `/api/edrpou/{code}`) was removed
in 2026 and the whole site now sits behind a Cloudflare challenge, so we
parse the server-rendered HTML through `fetch_with_bot_bypass`
(httpx first, FlareSolverr fallback):

    Search: https://clarity-project.info/edrs?query={query}
    Detail: https://clarity-project.info/edr/{code}

Identifier: EDRPOU — 8 digits. Ukrainian VAT numbers are 12 digits;
practical lookups against the registry still hinge on EDRPOU, so VAT is
normalized down to its embedded EDRPOU when possible.

Financials: Ukraine has no free centralized annual-report dataset for the
general population, but SMIDA (smida.gov.ua) — the NSSMC-run securities
disclosure system — publishes the filed regular (annual) reports of every
company that has issued securities. The issuer profile lives at
`/db/prof/{edrpou}`; its "Регулярна інформація" reports are loaded from the
AJAX fragment `/db/prof/tabs/{edrpou}/regularXml`, which lists each filed
report with its year, period type and a per-filing viewer URL. We parse
that table and return one `FinancialFiling` per annual report, pointing
`document_url` at the real per-company filing page. Non-issuers (the
majority of LLCs) have no profile and return an empty list. No mock numbers.
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime
from urllib.parse import quote

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, fetch_with_bot_bypass, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_EDRPOU_RE = re.compile(r"^\d{1,10}$")
_VAT_RE = re.compile(r"^\d{10,12}$")
_TAG_RE = re.compile(r"<[^>]+>")

_PROBE_EDRPOU = "20077720"  # Naftogaz of Ukraine — used for health probes.

_SEARCH_CARD_RE = re.compile(
    r'<a[^>]+href="/edr/(\d{6,10})"[^>]*>(.*?)</a>.*?'
    r'ЄДРПОУ:\s*\1</div>\s*'
    r'(?:<div[^>]*class="address[^"]*"[^>]*>(.*?)</div>)?',
    re.S,
)

_SMIDA_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_SMIDA_YEAR_HREF_RE = re.compile(r'href="(/db/emitent/report/year/xml/show/\d+)"')
_SMIDA_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _normalize_edrpou(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if cleaned.upper().startswith("UA"):
        cleaned = cleaned[2:]
    if not _EDRPOU_RE.match(cleaned):
        raise InvalidIdentifierError(f"EDRPOU must be up to 10 digits: {value}")
    # Standard EDRPOU is 8 digits; short codes belong to legacy state bodies
    # and are left-padded by convention.
    if len(cleaned) < 8:
        cleaned = cleaned.zfill(8)
    return cleaned


def _normalize_vat_to_edrpou(value: str) -> str:
    cleaned = value.strip().replace(" ", "").upper()
    if cleaned.startswith("UA"):
        cleaned = cleaned[2:]
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(f"Ukrainian VAT must be 10–12 digits: {value}")
    # For a legal entity the first 8 digits of the 12-digit VAT (or all 10 of
    # a 10-digit individual code) correspond to its EDRPOU. We try the most
    # informative prefix first.
    return _normalize_edrpou(cleaned[:8] if len(cleaned) >= 8 else cleaned)


def _strip_tags(fragment: str) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", fragment)).strip()


def _squash_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,|")


class UAAdapter(CountryAdapter):
    country_code = "UA"
    country_name = "Ukraine"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://clarity-project.info"
    SMIDA_BASE = "https://smida.gov.ua"
    SMIDA_PROFILE_URL = "https://smida.gov.ua/db/prof/{code}"
    SMIDA_REPORTS_TAB_URL = "https://smida.gov.ua/db/prof/tabs/{code}/regularXml"

    async def _fetch_page(self, path: str) -> tuple[str, int]:
        text, status, _source = await fetch_with_bot_bypass(
            f"{self.BASE_URL}{path}", timeout=30.0
        )
        return text, status

    async def health_check(self) -> AdapterHealth:
        try:
            page, status = await self._fetch_page(f"/edr/{_PROBE_EDRPOU}")
            if status >= 500 or _PROBE_EDRPOU not in page:
                raise RuntimeError(f"Clarity Project HTTP {status}")
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
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via Clarity Project HTML (open data mirror of YeDR), "
                "Cloudflare-walled — FlareSolverr fallback required. "
                "Financials via SMIDA regular annual reports (securities issuers only)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        page, status = await self._fetch_page(f"/edrs?query={quote(name)}")
        if status == 404:
            return []
        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for m in _SEARCH_CARD_RE.finditer(page):
            code, name_html, address_html = m.group(1), m.group(2), m.group(3)
            try:
                edrpou = _normalize_edrpou(code)
            except InvalidIdentifierError:
                continue
            if edrpou in seen:
                continue
            company_name = _squash_spaces(_strip_tags(name_html))
            if not company_name:
                continue
            seen.add(edrpou)
            matches.append(
                CompanyMatch(
                    id=edrpou,
                    name=company_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=edrpou,
                            label="EDRPOU",
                        )
                    ],
                    address=_squash_spaces(_strip_tags(address_html)) if address_html else None,
                    status=None,
                    source_url=f"{self.BASE_URL}/edr/{edrpou}",
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            edrpou = _normalize_edrpou(value)
        elif id_type == IdentifierType.VAT:
            edrpou = _normalize_vat_to_edrpou(value)
        else:
            raise InvalidIdentifierError(
                f"UA only supports COMPANY_NUMBER (EDRPOU) or VAT, got {id_type}"
            )

        page, status = await self._fetch_page(f"/edr/{edrpou}")
        if status == 404:
            return None

        fields = _parse_edr_info(page)
        name = (
            fields.get("Назва")
            or fields.get("Назва англійською мовою")
            or _h1_text(page)
        )
        if not name:
            return None

        director_name = fields.get("Керівник")
        directors = (
            [Director(name=director_name, role="керівник")] if director_name else []
        )

        return CompanyDetails(
            id=edrpou,
            name=name,
            country=self.country_code,
            legal_form=fields.get("Організаційна форма"),
            status=_map_status(fields.get("Стан")),
            incorporation_date=_parse_date(fields.get("Дата реєстрації")),
            registered_address=fields.get("Адреса"),
            capital_amount=_parse_capital(fields.get("Статутний капітал")),
            capital_currency="UAH",
            nace_codes=[],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=edrpou,
                    label="EDRPOU",
                ),
            ],
            directors=directors,
            raw={"edr_info": fields},
            source_url=f"{self.BASE_URL}/edr/{edrpou}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        edrpou = _normalize_edrpou(company_id)
        tab_url = self.SMIDA_REPORTS_TAB_URL.format(code=edrpou)
        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, tab_url)
            except Exception:
                return []
        if resp.status_code != 200:
            return []

        profile_url = self.SMIDA_PROFILE_URL.format(code=edrpou)
        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for year, report_path in _parse_smida_annual_reports(resp.text):
            if year in seen_years:
                continue
            seen_years.add(year)
            filings.append(
                FinancialFiling(
                    company_id=edrpou,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="UAH",
                    document_url=f"{self.SMIDA_BASE}{report_path}",
                    document_format="html",
                    source_url=profile_url,
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings[:years]


def _parse_smida_annual_reports(fragment: str) -> list[tuple[int, str]]:
    """Extract (year, report_path) pairs for each annual filing.

    Rows in the `regularXml` tab render as `date | year | quarter | type |
    view-link`; annual filings carry the type "Річна" and a link under
    `/db/emitent/report/year/xml/show/{id}`.
    """
    reports: list[tuple[int, str]] = []
    for row in _SMIDA_ROW_RE.finditer(fragment):
        block = row.group(1)
        if "Річна" not in block:
            continue
        href = _SMIDA_YEAR_HREF_RE.search(block)
        if not href:
            continue
        year: int | None = None
        for cell in _SMIDA_CELL_RE.findall(block):
            text = _squash_spaces(_strip_tags(cell))
            if _YEAR_RE.match(text):
                year = int(text)
                break
        if year is None:
            continue
        reports.append((year, href.group(1)))
    return reports


def _parse_edr_info(page: str) -> dict[str, str]:
    """Flatten the first `edr-info` table into a label → value dict.

    Rows render as `<tr><td>Label:</td><td>value ...</td></tr>`; values can
    contain nested markup, so we strip tags per cell and join the rest.
    """
    table_match = re.search(
        r'<table class="[^"]*edr-info[^"]*".*?</table>', page, re.S
    )
    if not table_match:
        return {}
    fields: dict[str, str] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_match.group(0), re.S):
        cells = [
            _squash_spaces(_strip_tags(c))
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        ]
        cells = [c for c in cells if c]
        if len(cells) < 2 or not cells[0].endswith(":"):
            continue
        label = cells[0].rstrip(":").strip()
        value = _squash_spaces(" ".join(cells[1:]))
        # Clarity masks parts of addresses/names for anonymous sessions and
        # repeats the raw ЄДР record copy after the display value.
        value = _squash_spaces(value.replace("*", " ").split("Запис в ЄДР")[0])
        if label and value and label not in fields:
            fields[label] = value
    return fields


def _h1_text(page: str) -> str | None:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not m:
        return None
    return _squash_spaces(_strip_tags(m.group(1))) or None


def _map_status(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    if "зареєстровано" in lowered:
        return "active"
    if "припин" in lowered:
        return "ceased"
    return value


def _parse_capital(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"[\d\s]+(?:[.,]\d+)?", value)
    if not m:
        return None
    try:
        return float(m.group(0).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    text = s.strip()
    m = re.search(r"\d{2}\.\d{2}\.\d{4}", text)
    if m:
        try:
            return datetime.strptime(m.group(0), "%d.%m.%Y").date()
        except ValueError:
            return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
