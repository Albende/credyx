"""Hungary adapter — e-beszamolo (Ministry of Justice) + VIES (VAT).

Free public sources only, no API key:

- e-beszamolo (``e-beszamolo.im.gov.hu``) is the official Ministry of Justice
  electronic annual-report portal. Every Hungarian company files its balance
  sheets / annual reports here and they are downloadable for free. The search
  form is guarded by an ALTCHA proof-of-work challenge (a solvable SHA-256
  PoW, not a human CAPTCHA) plus a one-shot "accept terms of use" session
  flag — both of which we satisfy programmatically:

    1. ``GET  /oldal/beszamolo_kereses``      establish the session cookie
    2. ``POST /Search/AcceptTermsOfUse``      set the terms-accepted flag
    3. ``GET  /altcha/api/v1/challenge``      fetch a PoW challenge
    4. solve the PoW, ``POST /Search/Results``  run the search
    5. ``POST /oldal/kereses_merleglista``    list a company's filings

  This drives name search, company-number lookup, and the filed annual
  reports (period, publication date, and the per-document download URLs).

- VIES REST (``ec.europa.eu/.../vies``) resolves a Hungarian VAT number to the
  registered company name + address. Used for ``lookup_by_identifier(VAT)``.

The paid e-cégjegyzék / opten / ceginfo services are out of scope (MVP rule).

Identifiers:
- Cégjegyzékszám (Company Registry Number): NN-NN-NNNNNN (2-2-6 digits).
- Adószám (Tax ID): 11 digits, first 8 are the "törzsszám" used in VAT.
- VAT: "HU" + first 8 digits of Adószám.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import re
from datetime import date
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

# Cégjegyzékszám: 10 digits split as 2-2-6.
_CEGJEGYZEKSZAM_RE = re.compile(r"^(\d{2})-?(\d{2})-?(\d{6})$")
# Hungarian Adószám / VAT törzsszám: 8 digits.
_HU_VAT_DIGITS_RE = re.compile(r"^\d{8}$")
# Full Adószám: 11 digits (8 + 1 VAT code + 2 area code).
_ADOSZAM_RE = re.compile(r"^\d{11}$")

_HU_MONTHS = {
    "január": 1, "február": 2, "március": 3, "április": 4,
    "május": 5, "június": 6, "július": 7, "augusztus": 8,
    "szeptember": 9, "október": 10, "november": 11, "december": 12,
}

# Period line, e.g. "2024. január 01. - 2024. december 31."
_PERIOD_RE = re.compile(
    r"(\d{4})\.\s*([a-záéíóöőúüű]+)\s*(\d{1,2})\.\s*[-–]\s*"
    r"(\d{4})\.\s*([a-záéíóöőúüű]+)\s*(\d{1,2})\.",
    re.IGNORECASE,
)
_PUBLISHED_RE = re.compile(r"Közzétéve:\s*(\d{4})\.\s*(\d{2})\.\s*(\d{2})\.")
_ATTACHMENT_RE = re.compile(
    r'href="(https://e-beszamolo\.im\.gov\.hu/oldal/kereses_megjelenites\?[^"]+)"'
    r'[^>]*>\s*([^<]+?)\s*\(([\d\s]+)kB\)',
)


def _normalize_cegjegyzekszam(value: str) -> str:
    """Normalize Cégjegyzékszám to canonical NN-NN-NNNNNN form."""
    cleaned = value.strip().replace(" ", "")
    m = _CEGJEGYZEKSZAM_RE.match(cleaned)
    if not m:
        raise InvalidIdentifierError(
            f"Hungarian Cégjegyzékszám must be NN-NN-NNNNNN (10 digits): {value}"
        )
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _normalize_hu_vat(value: str) -> str:
    """Normalize a Hungarian VAT to its 8-digit törzsszám form.

    Accepts ``HU12345678``, ``12345678``, or a full 11-digit Adószám (the
    first 8 digits are the VAT törzsszám).
    """
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("HU"):
        cleaned = cleaned[2:]
    if _ADOSZAM_RE.match(cleaned):
        cleaned = cleaned[:8]
    if not _HU_VAT_DIGITS_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Hungarian VAT must be HU + 8 digits (or 11-digit Adószám): {value}"
        )
    return cleaned


def _solve_altcha(challenge: dict[str, Any]) -> str:
    """Solve an ALTCHA SHA-256 proof-of-work and return the base64 payload.

    The server publishes ``salt``, ``challenge`` (the target hex digest) and
    ``maxnumber``; the answer is the integer ``n`` such that
    ``sha256(salt + n).hexdigest() == challenge``.
    """
    salt = challenge["salt"]
    target = challenge["challenge"]
    for n in range(int(challenge.get("maxnumber", 100000)) + 1):
        if hashlib.sha256(f"{salt}{n}".encode()).hexdigest() == target:
            payload = {
                "algorithm": challenge["algorithm"],
                "challenge": target,
                "number": n,
                "salt": salt,
                "signature": challenge["signature"],
            }
            return base64.b64encode(json.dumps(payload).encode()).decode()
    raise httpx.HTTPError("ALTCHA proof-of-work had no solution in range")


class HUAdapter(CountryAdapter):
    country_code = "HU"
    country_name = "Hungary"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 20

    VIES_BASE_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api"
    EBESZAMOLO_BASE_URL = "https://e-beszamolo.im.gov.hu"
    SEARCH_PAGE_URL = "https://e-beszamolo.im.gov.hu/oldal/beszamolo_kereses"
    # A known-valid HU VAT (OTP Bank) used for liveness probe.
    HEALTH_PROBE_VAT = "10537914"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.EBESZAMOLO_BASE_URL
            ) as client:
                resp = await get_with_retry(client, "/oldal/beszamolo_kereses")
                resp.raise_for_status()
                if "rcForm" not in resp.text:
                    raise RuntimeError("e-beszamolo search form not present")
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
                "Name search, Cégjegyzékszám lookup and filed annual reports via "
                "e-beszamolo.im.gov.hu (ALTCHA proof-of-work solved key-free); "
                "VAT lookup via VIES."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = name.strip()
        if len(term) < 4:
            raise InvalidIdentifierError(
                "e-beszamolo name search requires at least 4 characters"
            )
        async with self._ebeszamolo_client() as client:
            rows = await self._search(client, firm_name=term)
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            matches.append(
                CompanyMatch(
                    id=row["cegjegyzekszam"],
                    name=row["name"],
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=row["cegjegyzekszam"],
                            label="Cégjegyzékszám",
                        )
                    ],
                    source_url=self.SEARCH_PAGE_URL,
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_cegjegyzekszam(value)
        raise InvalidIdentifierError(
            f"HU only supports VAT and COMPANY_NUMBER, got {id_type}"
        )

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_hu_vat(value)
        async with build_http_client(base_url=self.VIES_BASE_URL) as client:
            resp = await get_with_retry(client, f"/ms/HU/vat/{vat}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        if not data.get("isValid", data.get("valid")):
            return None
        raw_name = (data.get("name") or "").strip()
        raw_addr = (data.get("address") or "").strip()
        name = "" if raw_name in {"", "---"} else raw_name
        addr = None if raw_addr in {"", "---"} else _clean_address(raw_addr)
        return CompanyDetails(
            id=vat,
            name=name,
            country="HU",
            registered_address=addr,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=f"HU{vat}", label="Adószám (VAT)"
                ),
            ],
            raw=data,
            source_url=f"https://ec.europa.eu/taxation_customs/vies/?vat=HU{vat}",
        )

    async def _lookup_by_cegjegyzekszam(self, value: str) -> CompanyDetails | None:
        cj = _normalize_cegjegyzekszam(value)
        async with self._ebeszamolo_client() as client:
            rows = await self._search(client, firm_number=cj)
        match = next((r for r in rows if r["cegjegyzekszam"] == cj), None)
        if match is None:
            return None
        return CompanyDetails(
            id=cj,
            name=match["name"],
            country="HU",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=cj,
                    label="Cégjegyzékszám",
                ),
            ],
            source_url=self.SEARCH_PAGE_URL,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cj = _normalize_cegjegyzekszam(company_id)
        async with self._ebeszamolo_client() as client:
            rows = await self._search(client, firm_number=cj)
            match = next((r for r in rows if r["cegjegyzekszam"] == cj), None)
            if match is None:
                return []
            list_html = await self._filing_list(client, match["code"])
        filings = _parse_filings(cj, list_html)
        if years and years > 0:
            keep_years = sorted({f.year for f in filings}, reverse=True)[:years]
            filings = [f for f in filings if f.year in keep_years]
        return filings

    def _ebeszamolo_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.EBESZAMOLO_BASE_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )

    async def _search(
        self,
        client: httpx.AsyncClient,
        *,
        firm_number: str = "",
        firm_name: str = "",
        firm_tax: str = "",
    ) -> list[dict[str, str]]:
        await client.get("/oldal/beszamolo_kereses")
        await client.post(
            "/Search/AcceptTermsOfUse",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        challenge = (await client.get("/altcha/api/v1/challenge")).json()
        altcha = _solve_altcha(challenge)
        resp = await client.post(
            "/Search/Results",
            files={
                "firmNumber": (None, firm_number),
                "firmTaxNumber": (None, firm_tax),
                "firmName": (None, firm_name),
                "altcha": (None, altcha),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        resp.raise_for_status()
        body = resp.text
        if "search-result-error" in body:
            message = re.sub(r"<[^>]+>", " ", body)
            raise httpx.HTTPError(
                f"e-beszamolo search rejected: {html.unescape(message).strip()[:160]}"
            )
        return _parse_search_rows(body)

    async def _filing_list(self, client: httpx.AsyncClient, code: str) -> str:
        resp = await client.post(
            "/oldal/kereses_merleglista", data={"f": code, "so": "1"}
        )
        resp.raise_for_status()
        return resp.text


_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_NAME_CELL_RE = re.compile(
    r'firm-name-col.*?<a[^>]*>(.*?)</a>', re.S
)
_REG_CELL_RE = re.compile(r'firm-reg-num-col.*?<a[^>]*>(.*?)</a>', re.S)
_DATA_CODE_RE = re.compile(r'data-code="([^"]+)"')
_BR_RE = re.compile(r"<br\s*/?>")


def _parse_search_rows(body: str) -> list[dict[str, str]]:
    table_match = re.search(
        r'id="search-result-table".*?<tbody>(.*?)</tbody>', body, re.S
    )
    if not table_match:
        return []
    rows: list[dict[str, str]] = []
    for row_html in _ROW_RE.findall(table_match.group(1)):
        code_m = _DATA_CODE_RE.search(row_html)
        name_m = _NAME_CELL_RE.search(row_html)
        reg_m = _REG_CELL_RE.search(row_html)
        if not (code_m and name_m and reg_m):
            continue
        names = [
            html.unescape(part).strip()
            for part in _BR_RE.split(name_m.group(1))
            if part.strip()
        ]
        cegjegyzekszam = html.unescape(reg_m.group(1)).strip()
        if not names or not _CEGJEGYZEKSZAM_RE.match(cegjegyzekszam.replace("-", "")):
            continue
        rows.append(
            {
                "name": names[-1],
                "cegjegyzekszam": cegjegyzekszam,
                "code": code_m.group(1),
            }
        )
    return rows


def _parse_filings(cegjegyzekszam: str, list_html: str) -> list[FinancialFiling]:
    filings: list[FinancialFiling] = []
    chunks = list_html.split('<div class="balance-container')
    for raw_chunk in chunks[1:]:
        header, _, _ = raw_chunk.partition('data-search-order')
        if "invalid" in header:
            continue
        chunk = html.unescape(raw_chunk)
        period = _PERIOD_RE.search(chunk)
        if not period:
            continue
        end_year = int(period.group(4))
        end_month = _HU_MONTHS.get(period.group(5).lower())
        end_day = int(period.group(6))
        period_end: date | None = None
        if end_month:
            try:
                period_end = date(end_year, end_month, end_day)
            except ValueError:
                period_end = None

        published_m = _PUBLISHED_RE.search(chunk)
        published = (
            f"{published_m.group(1)}-{published_m.group(2)}-{published_m.group(3)}"
            if published_m
            else None
        )

        kind_m = re.search(r"<p>([^<]+)</p>", chunk)
        report_kind = html.unescape(kind_m.group(1)).strip() if kind_m else None

        attachments = [
            {
                "filename": html.unescape(fname).strip(),
                "size_kb": int(size.replace(" ", "")),
                "download_url": html.unescape(url),
            }
            for url, fname, size in _ATTACHMENT_RE.findall(chunk)
        ]
        document_format = None
        if attachments:
            ext = attachments[0]["filename"].rsplit(".", 1)[-1].lower()
            document_format = ext if ext in {"pdf", "zip", "xml", "xbrl"} else None

        structured = {
            "period": f"{period.group(1)}.{period.group(2)} {period.group(3)}. - "
            f"{period.group(4)}.{period.group(5)} {period.group(6)}.",
            "report_kind": report_kind,
            "published_on": published,
            "cegjegyzekszam": cegjegyzekszam,
            "attachments": attachments,
            "source": "e-beszamolo.im.gov.hu",
            "note": (
                "Download URLs require an active e-beszamolo search session "
                "(terms accepted + ALTCHA solved) issued during fetch."
            ),
        }
        filings.append(
            FinancialFiling(
                company_id=cegjegyzekszam,
                year=end_year,
                type=FilingType.ANNUAL_REPORT,
                period_end=period_end,
                currency=None,
                structured_data=structured,
                document_url=None,
                document_format=document_format,
                source_url=HUAdapter.SEARCH_PAGE_URL,
            )
        )
    return filings


def _clean_address(addr: str) -> str:
    collapsed = re.sub(r"\s+", " ", addr.replace("\n", " ").replace("\r", " "))
    return collapsed.strip()
