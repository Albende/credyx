"""Moldova adapter — idno.md registry mirror + statistica.md filings depository.

Two free, public, key-free sources are stitched together:

  * https://www.idno.md/ — community mirror of the ASP (Agenția Servicii
    Publice) state company register, keyed by IDNO. Used for name search and
    per-identifier lookup. The site sits behind Cloudflare, so requests go
    through ``fetch_with_bot_bypass`` (FlareSolverr fallback).
  * https://depozitar.statistica.md/ — the official Public Depository of
    Financial Statements run by the National Bureau of Statistics. Its
    ``/api/public/v1`` backend exposes filed annual financial statements per
    IDNO without an API key (the reCAPTCHA-gated ``/fs`` and ``/ae`` search
    endpoints are not used — the ``/fs/economic-agent`` listing and
    ``/fs/{id}`` detail endpoints are token-free).

Identifier: IDNO — 13 digits, also serves as the corporate tax number
(fiscal code). The first digit encodes the legal form (1 = SRL/SA/etc.).
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import date
from typing import Any
from urllib.parse import quote

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import (
    build_http_client,
    fetch_with_bot_bypass,
    get_with_retry,
)
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

_IDNO_RE = re.compile(r"^\d{13}$")

IDNO_SITE = "https://www.idno.md"
DEPOZITAR_SITE = "https://depozitar.statistica.md"
DEPOZITAR_API = "https://depozitar-cabinet.statistica.md/api/public/v1"

_DEPOZITAR_HEADERS = {
    "Origin": DEPOZITAR_SITE,
    "Referer": DEPOZITAR_SITE + "/",
    "Accept": "application/json",
}

_COMPANY_LINK_RE = re.compile(
    r'href="/?companie\?idno=(\d{13})[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_BALANCE_SHEET_CODES = {
    "230": "total_non_current_assets",
    "420": "total_current_assets",
    "430": "total_assets",
    "490": "share_capital",
    "570": "net_profit",
    "620": "total_equity",
    "700": "total_non_current_liabilities",
    "820": "total_current_liabilities",
    "880": "total_equity_and_liabilities",
}
_INCOME_STATEMENT_CODES = {
    "010": "revenue",
    "020": "cost_of_sales",
    "030": "gross_profit",
    "080": "operating_result",
}


def _normalize_idno(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("MD"):
        cleaned = cleaned[2:]
    if not _IDNO_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Moldovan IDNO must be 13 digits, got: {value}"
        )
    return cleaned


class MDAdapter(CountryAdapter):
    country_code = "MD"
    country_name = "Moldova"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        try:
            _, status, _ = await fetch_with_bot_bypass(f"{IDNO_SITE}/")
            reachable = status < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if reachable else AdapterStatus.DEGRADED,
            capabilities={"search": reachable, "lookup": reachable, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search/lookup scrape idno.md via Cloudflare bypass; financials "
                "come from the official statistica.md filings depository."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        url = f"{IDNO_SITE}/companii?q={quote(name.strip())}"
        html, status, _ = await fetch_with_bot_bypass(url)
        if status >= 400:
            return []
        return _parse_search_results(html, limit=limit)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"Moldova supports COMPANY_NUMBER/VAT (IDNO), got {id_type}"
            )
        idno = _normalize_idno(value)
        url = f"{IDNO_SITE}/companie?idno={idno}"
        html, status, _ = await fetch_with_bot_bypass(url)
        if status >= 400:
            return None
        return _parse_detail_page(html, idno)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        idno = _normalize_idno(company_id)
        async with build_http_client(headers=_DEPOZITAR_HEADERS) as client:
            resp = await get_with_retry(
                client, f"{DEPOZITAR_API}/fs/economic-agent?idno={idno}"
            )
            if resp.status_code != 200:
                return []
            listing = resp.json()
            if not isinstance(listing, list) or not listing:
                return []
            listing.sort(key=lambda r: r.get("year", 0), reverse=True)

            filings: list[FinancialFiling] = []
            for entry in listing[:years]:
                statement_id = entry.get("id")
                year = entry.get("year")
                if not statement_id or not year:
                    continue
                detail = await get_with_retry(
                    client, f"{DEPOZITAR_API}/fs/{statement_id}"
                )
                payload = detail.json() if detail.status_code == 200 else {}
                filings.append(
                    _build_filing(idno, str(statement_id), int(year), payload)
                )
        return filings


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s)


def _clean(s: str) -> str:
    return html_lib.unescape(re.sub(r"\s+", " ", _strip_tags(s)).strip())


def _parse_search_results(html: str, *, limit: int) -> list[CompanyMatch]:
    matches: list[CompanyMatch] = []
    seen: set[str] = set()
    for m in _COMPANY_LINK_RE.finditer(html):
        idno = m.group(1)
        if idno in seen:
            continue
        name = _clean(m.group(2))
        if not name:
            continue
        seen.add(idno)
        matches.append(
            CompanyMatch(
                id=idno,
                name=name,
                country="MD",
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER, value=idno, label="IDNO"
                    ),
                ],
                source_url=f"{IDNO_SITE}/companie?idno={idno}",
            )
        )
        if len(matches) >= limit:
            break
    return matches


def _field_after(html: str, *labels: str) -> str | None:
    for label in labels:
        pat = (
            rf"<h4[^>]*>\s*{re.escape(label)}[^<]*</h4>\s*<(?:p|h3)[^>]*>(.*?)</(?:p|h3)>"
        )
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            val = _clean(m.group(1))
            if val:
                return val
    return None


def _parse_ro_date(value: str | None) -> date | None:
    if not value:
        return None
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", value)
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def _parse_detail_page(html: str, idno: str) -> CompanyDetails | None:
    if idno not in html:
        return None
    name = _field_after(html, "Denumire")
    if not name:
        return None

    legal_form = _field_after(html, "Forma organizatorico-juridică", "Forma juridică")
    status = _field_after(html, "Statutul", "Statut")
    address = _field_after(html, "Adresa juridică", "Adresa")
    inc_date = _parse_ro_date(_field_after(html, "Data inregistrării", "Data înregistrării"))

    nace_codes: list[str] = []
    act_m = re.search(
        r"Genurile de activitate nelicen.*?(?:Genurile de activitate licen|</div>\s*</div>\s*</div>)",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if act_m:
        nace_codes = re.findall(r'companii\?q=(\d{4,5})"', act_m.group(0))

    return CompanyDetails(
        id=idno,
        name=name,
        country="MD",
        legal_form=legal_form,
        status=status,
        incorporation_date=inc_date,
        registered_address=address,
        nace_codes=nace_codes[:5],
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=idno, label="IDNO"
            ),
            RegistryIdentifier(
                type=IdentifierType.VAT, value=idno, label="Cod fiscal"
            ),
        ],
        raw={"source": "idno.md"},
        source_url=f"{IDNO_SITE}/companie?idno={idno}",
    )


def _parse_amount(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace(" ", "").replace(" ", "").strip()
    if not cleaned or not re.fullmatch(r"-?\d+", cleaned):
        return None
    return int(cleaned)


def _extract_group(payload: dict[str, Any], group_code: str, code_map: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for group in payload.get("groups", []) or []:
        if group.get("code") != group_code:
            continue
        for field in group.get("fields", []) or []:
            key = code_map.get(str(field.get("code")))
            if key is None:
                continue
            amount = _parse_amount(field.get("dateCurrent"))
            if amount is not None:
                out[key] = amount
    return out


def _build_filing(
    idno: str, statement_id: str, year: int, payload: dict[str, Any]
) -> FinancialFiling:
    period_end = None
    period_to = payload.get("periodTo")
    if isinstance(period_to, str):
        try:
            period_end = date.fromisoformat(period_to[:10])
        except ValueError:
            period_end = None

    structured: dict[str, Any] = {
        "source": payload.get("source"),
        "doctype": payload.get("doctype"),
        "period_from": payload.get("periodFrom"),
        "period_to": period_to,
        "declaration_date": payload.get("declarationDate"),
    }
    caem = (payload.get("legalEntity") or {}).get("caem") or {}
    if caem.get("code"):
        structured["caem"] = caem.get("code")
    balance_sheet = _extract_group(payload, "anexa1", _BALANCE_SHEET_CODES)
    income_statement = _extract_group(payload, "anexa2", _INCOME_STATEMENT_CODES)
    if balance_sheet:
        structured["balance_sheet"] = balance_sheet
    if income_statement:
        structured["income_statement"] = income_statement

    return FinancialFiling(
        company_id=idno,
        year=year,
        type=FilingType.ANNUAL_REPORT,
        period_end=period_end,
        currency="MDL",
        structured_data=structured or None,
        document_url=f"{DEPOZITAR_API}/fs/{statement_id}",
        document_format="json",
        source_url=f"{DEPOZITAR_SITE}/search/financial-statement/{statement_id}",
    )
