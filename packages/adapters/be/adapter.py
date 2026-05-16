"""Belgium adapter — KBO/BCE (registry) + NBB CBSO (annual accounts).

Two free public sources, no auth, no API key:

- KBO/BCE public consult page (HTML scrape) for the registered-entity record:
    https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?ondernemingsnummer={n}&lang=en
- National Bank of Belgium "Consult" service (JSON) for filed annual accounts:
    list:    https://consult.cbso.nbb.be/api/rs-consult/published-deposits
              ?enterpriseNumber={n}&page=0&size=50&sort=periodEndDate,desc
    pdf:     https://consult.cbso.nbb.be/api/external/broker/public/deposits/pdf/{id}
    company: https://consult.cbso.nbb.be/api/rs-consult/companies/{n}/EN
    search:  https://consult.cbso.nbb.be/api/rs-consult/companies/search
              ?companyName={q}&language=EN&postalCode=&phonetic=false&exact=false

The Belgian "enterprise number" (10 digits, formatted NNNN.NNN.NNN) doubles as
the VAT number when prefixed with "BE", so the primary identifier here is VAT.

Name search is supported via the NBB "Consult" search endpoint, which matches
words in the registered name. KBO's own free-text search lives behind a CAPTCHA
on kbopub and is intentionally not used here.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
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

logger = logging.getLogger(__name__)

_ENT_RE = re.compile(r"^[01]\d{9}$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NACE_RE = re.compile(
    r"nace\.code=(\d{3,5})[^>]*>\s*([\d.]+)\s*</a>\s*&nbsp;-&nbsp;\s*([^<\n]+)",
    re.IGNORECASE,
)


def _normalize_enterprise_number(value: str) -> str:
    """Strip BE prefix, dots, spaces → bare 10-digit enterprise number."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "").replace("-", "")
    if cleaned.startswith("BE"):
        cleaned = cleaned[2:]
    if len(cleaned) == 9:
        cleaned = "0" + cleaned
    if not _ENT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"BE enterprise number must be 10 digits starting with 0 or 1: {value}"
        )
    return cleaned


def _format_dotted(bare: str) -> str:
    return f"{bare[:4]}.{bare[4:7]}.{bare[7:]}"


class BEAdapter(CountryAdapter):
    country_code = "BE"
    country_name = "Belgium"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    KBO_DETAIL_URL = (
        "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html"
        "?ondernemingsnummer={n}&lang=en"
    )
    CBSO_BASE = "https://consult.cbso.nbb.be"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.CBSO_BASE) as client:
                resp = await get_with_retry(client, "/api/rs-consult/version")
                if resp.status_code >= 400:
                    raise AdapterError(f"CBSO version returned {resp.status_code}")
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
                "Name search uses NBB CBSO; lookup uses KBO public page; "
                "financials are NBB CBSO published deposits (PDF)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        params = {
            "companyName": name,
            "language": "EN",
            "postalCode": "",
            "phonetic": "false",
            "exact": "false",
        }
        async with build_http_client(
            base_url=self.CBSO_BASE,
            headers={"Accept": "application/json", "Referer": f"{self.CBSO_BASE}/"},
        ) as client:
            resp = await get_with_retry(client, "/api/rs-consult/companies/search", params=params)
            if resp.status_code == 400:
                return []
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, list):
            return []
        matches: list[CompanyMatch] = []
        for row in data[:limit]:
            ent = row.get("cbe")
            if not ent:
                continue
            try:
                bare = _normalize_enterprise_number(ent)
            except InvalidIdentifierError:
                continue
            matches.append(
                CompanyMatch(
                    id=bare,
                    name=row.get("name") or "",
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT,
                            value=f"BE{bare}",
                            label="VAT",
                        ),
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=_format_dotted(bare),
                            label="Enterprise number",
                        ),
                    ],
                    address=_address_from_search_row(row),
                    status=row.get("legalSituation"),
                    source_url=f"{self.CBSO_BASE}/consult-enterprise/{bare}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"BE supports VAT or COMPANY_NUMBER, got {id_type}"
            )
        bare = _normalize_enterprise_number(value)

        url = self.KBO_DETAIL_URL.format(n=bare)
        async with build_http_client() as client:
            resp = await get_with_retry(client, url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            html_text = resp.text

        if "Registered entity data" not in html_text and "No data" in html_text:
            return None
        if "Registered entity data" not in html_text:
            raise AdapterError("Unexpected KBO response shape — page structure may have changed")

        details = _parse_kbo_html(html_text, bare)
        details.source_url = url.replace("&lang=en", "&lang=en")
        return details

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        bare = _normalize_enterprise_number(company_id)
        cutoff_year = datetime.utcnow().year - years
        params = {
            "enterpriseNumber": bare,
            "page": 0,
            "size": 100,
            "sort": ["periodEndDate,desc", "depositDate,desc"],
        }
        async with build_http_client(
            base_url=self.CBSO_BASE,
            headers={"Accept": "application/json", "Referer": f"{self.CBSO_BASE}/"},
        ) as client:
            resp = await get_with_retry(client, "/api/rs-consult/published-deposits", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()

        rows = payload.get("content", []) if isinstance(payload, dict) else []
        filings: list[FinancialFiling] = []
        for row in rows:
            deposit_id = row.get("id")
            if not deposit_id:
                continue
            period_end = _parse_iso_date(row.get("periodEndDate"))
            year = row.get("periodEndDateYear") or (period_end.year if period_end else None)
            if not year:
                continue
            if year < cutoff_year:
                continue
            currency = ((row.get("currency") or {}).get("code")) or "EUR"
            import_type = (row.get("importFileType") or "").lower() or "pdf"
            filings.append(
                FinancialFiling(
                    company_id=bare,
                    year=int(year),
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency=currency,
                    structured_data=None,
                    document_url=(
                        f"{self.CBSO_BASE}/api/external/broker/public/deposits/pdf/{deposit_id}"
                    ),
                    document_format="pdf" if import_type == "pdf" else import_type,
                    source_url=f"{self.CBSO_BASE}/consult-enterprise/{bare}",
                )
            )
        return filings


def _address_from_search_row(row: dict[str, Any]) -> str | None:
    parts = [
        " ".join(p for p in [row.get("streetName"), row.get("streetNumber")] if p),
        " ".join(p for p in [row.get("postalCode"), row.get("town")] if p),
        row.get("country"),
    ]
    cleaned = [p for p in parts if p and p.strip()]
    return ", ".join(cleaned) if cleaned else None


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


def _parse_english_date(s: str) -> date | None:
    m = re.match(r"^([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", s.strip())
    if not m:
        return None
    month = _MONTHS.get(m.group(1))
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def _strip_html(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    text = unescape(text).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def _row_text(html_text: str, label: str) -> str | None:
    """Extract the value cell text immediately after a KBO label cell.

    KBO puts each field as: `<td class="QL">Label:</td><td ...>VALUE</td>` with
    arbitrary whitespace. We capture the second cell and strip its HTML.
    """
    pattern = re.compile(
        r'<td[^>]*class="[QR]L"[^>]*>\s*' + re.escape(label) + r'\s*:?\s*</td>'
        r'\s*<td[^>]*>(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(html_text)
    if not m:
        return None
    return _strip_html(m.group(1))


def _parse_kbo_html(html_text: str, bare: str) -> CompanyDetails:
    name_raw = _row_text(html_text, "Name") or ""
    name = name_raw.split("Name in")[0].strip()
    if not name:
        name = name_raw.strip() or _format_dotted(bare)

    status = _row_text(html_text, "Status")
    legal_form_raw = _row_text(html_text, "Legal form") or ""
    legal_form = legal_form_raw.split("Since")[0].strip() or None

    start_raw = _row_text(html_text, "Start date") or ""
    incorporation_date = _parse_english_date(start_raw) if start_raw else None

    address_raw = _row_text(html_text, "Registered seat's address") or ""
    address = address_raw.split("Since")[0].strip() or None

    capital_amount = None
    capital_raw = _row_text(html_text, "Capital") or ""
    if capital_raw:
        m = re.search(r"([\d.]+(?:,\d+)?)\s*EUR", capital_raw)
        if m:
            try:
                capital_amount = float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                capital_amount = None

    nace_codes: list[str] = []
    for m in _NACE_RE.finditer(html_text):
        code = m.group(2).strip()
        if code and code not in nace_codes:
            nace_codes.append(code)

    directors = _parse_directors(html_text)

    return CompanyDetails(
        id=bare,
        name=name,
        country="BE",
        legal_form=legal_form,
        status=status,
        incorporation_date=incorporation_date,
        registered_address=address,
        capital_amount=capital_amount,
        capital_currency="EUR" if capital_amount is not None else None,
        nace_codes=nace_codes,
        identifiers=[
            RegistryIdentifier(type=IdentifierType.VAT, value=f"BE{bare}", label="VAT"),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=_format_dotted(bare),
                label="Enterprise number",
            ),
        ],
        directors=directors,
        raw={"kbo_html_bytes": len(html_text)},
    )


_DIRECTOR_ROW_RE = re.compile(
    r'<td[^>]*class="[QR]L"[^>]*>\s*([A-Za-z][A-Za-z .-]{2,40})\s*</td>'
    r'\s*<td[^>]*class="[QR]L"[^>]*>(.*?)</td>'
    r'\s*<td[^>]*class="[QR]L"[^>]*>\s*<span class="upd">\s*Since\s+([^<]+?)\s*</span>',
    re.DOTALL,
)


def _parse_directors(html_text: str) -> list[Director]:
    start = html_text.find('id="toonfctie"')
    if start == -1:
        return []
    end = html_text.find("</table>", start)
    block = html_text[start:end if end != -1 else len(html_text)]
    directors: list[Director] = []
    for m in _DIRECTOR_ROW_RE.finditer(block):
        role = m.group(1).strip()
        name_text = _strip_html(m.group(2))
        name = re.sub(r"\s+,\s+", " ", name_text).strip()
        if not name:
            continue
        appointed = _parse_english_date(m.group(3))
        directors.append(Director(name=name, role=role, appointed_on=appointed))
    return directors
