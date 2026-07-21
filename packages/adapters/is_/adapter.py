"""Iceland adapter — Skatturinn Fyrirtækjaskrá + Ársreikningaskrá.

Free public sources, no auth:

* **Skatturinn / RSK** (Iceland Revenue and Customs, https://www.skatturinn.is/)
  runs the official company register (Fyrirtækjaskrá), the annual-accounts
  register (Ársreikningaskrá) and the VAT register (VSK-skrá). All three are
  exposed through the public search at ``/fyrirtaekjaskra/leit/``:

  - Name search: ``/fyrirtaekjaskra/leit/?nafn={name}`` returns an HTML table
    of ``kennitala`` / name / address rows.
  - Per-kennitala detail: ``/fyrirtaekjaskra/leit/kennitala/{kennitala}``
    carries the registered name, incorporation date, legal form, domicile,
    ÍSAT activity classification, VAT number, directors and — under
    *Gögn úr ársreikningaskrá* — the list of every filed annual account
    (fiscal year, filing date, official account number, account type).

  The pages are HTML (no JSON API), so the adapter parses them. A kennitala
  that does not resolve to a company returns the bare search form; the
  adapter detects that and returns ``None`` / ``[]`` rather than fabricating.

  The actual annual-account PDFs are free but sit behind a stateful RSK
  web-shop checkout (add to cart → confirm → ASP.NET download postback), so
  there is no stable document URL to store. ``fetch_financials`` therefore
  returns real per-company filing metadata (year, type, filing date,
  official account number, registry source URL) with ``document_url`` left
  unset — never a generic landing page passed off as the filing.

Identifier: **kennitala**. 10 digits, conventionally rendered ``DDMMYY-NNNN``.
For legal persons the day component is the real day plus 40 (range 41–71).
We normalize by stripping an optional ``IS`` prefix, spaces and dashes, then
require exactly 10 digits.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
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


_KENNITALA_RE = re.compile(r"^\d{10}$")
_DEREGISTERED_MARKERS = ("afskrá", "afskra")


def _normalize_kennitala(value: str) -> str:
    """Strip dashes, spaces, and an optional ``IS`` prefix; require 10 digits."""
    if value is None:
        raise InvalidIdentifierError("Iceland kennitala cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("IS"):
        cleaned = cleaned[2:]
    if not _KENNITALA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Iceland kennitala must be exactly 10 digits, got: {value}"
        )
    return cleaned


def _format_kennitala(kt: str) -> str:
    """Return the canonical ``DDMMYY-NNNN`` display form."""
    return f"{kt[0:6]}-{kt[6:10]}"


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _parse_is_date(value: str) -> date | None:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


class ISAdapter(CountryAdapter):
    country_code = "IS"
    country_name = "Iceland"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    SKATTURINN_BASE = "https://www.skatturinn.is"
    SEARCH_PATH = "/fyrirtaekjaskra/leit/"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "is;q=0.9, en;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Referer": f"{self.SKATTURINN_BASE}{self.SEARCH_PATH}",
        }

    def _detail_url(self, kt: str) -> str:
        return f"{self.SKATTURINN_BASE}/fyrirtaekjaskra/leit/kennitala/{kt}"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.SKATTURINN_BASE,
                headers=self._headers(),
                timeout=15.0,
            ) as client:
                resp = await get_with_retry(
                    client, self.SEARCH_PATH, params={"nafn": "Marel"}
                )
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"skatturinn.is HTTP {resp.status_code}",
                    )
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
                "Skatturinn Fyrirtækjaskrá + Ársreikningaskrá parsed from the "
                "public HTML register. Financials return filed-account metadata; "
                "the PDFs sit behind a free stateful RSK web-shop checkout."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = (name or "").strip()
        if not query:
            return []
        async with build_http_client(
            base_url=self.SKATTURINN_BASE, headers=self._headers(), timeout=20.0
        ) as client:
            resp = await get_with_retry(
                client, self.SEARCH_PATH, params={"nafn": query}
            )
            resp.raise_for_status()
            html = resp.text

        detail = self._parse_detail(html)
        if detail is not None and "kennitala/" not in _results_table(html):
            return [
                CompanyMatch(
                    id=detail["kennitala"],
                    name=detail["name"],
                    country=self.country_code,
                    identifiers=self._identifiers(detail),
                    address=detail.get("address"),
                    status=detail.get("status"),
                    source_url=self._detail_url(detail["kennitala"]),
                )
            ]

        matches: list[CompanyMatch] = []
        for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", _results_table(html), re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
            if len(cells) < 2:
                continue
            kt_m = re.search(r"kennitala/(\d{10})", cells[0])
            if not kt_m:
                continue
            kt = kt_m.group(1)
            raw_name = _text(cells[1])
            status = self._status_from_name(raw_name)
            clean_name = re.sub(r"\(\s*Félag afskrá[^)]*\)", "", raw_name).strip(" ,")
            address = _text(cells[2]) if len(cells) > 2 else None
            matches.append(
                CompanyMatch(
                    id=kt,
                    name=clean_name or raw_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=_format_kennitala(kt),
                            label="Kennitala",
                        )
                    ],
                    address=address or None,
                    status=status,
                    source_url=self._detail_url(kt),
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
                f"Iceland supports VAT or COMPANY_NUMBER (kennitala), got {id_type}"
            )
        kt = _normalize_kennitala(value)
        html = await self._fetch_detail_html(kt)
        detail = self._parse_detail(html)
        if detail is None or detail["kennitala"] != kt:
            return None
        return CompanyDetails(
            id=kt,
            name=detail["name"],
            country=self.country_code,
            legal_form=detail.get("legal_form"),
            status=detail.get("status"),
            incorporation_date=detail.get("incorporation_date"),
            registered_address=detail.get("address"),
            nace_codes=detail.get("nace_codes", []),
            identifiers=self._identifiers(detail),
            directors=detail.get("directors", []),
            raw=detail.get("raw", {}),
            source_url=self._detail_url(kt),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        kt = _normalize_kennitala(company_id)
        html = await self._fetch_detail_html(kt)
        detail = self._parse_detail(html)
        if detail is None or detail["kennitala"] != kt:
            return []

        by_year: dict[int, dict[str, Any]] = {}
        for account in detail.get("accounts", []):
            year = account["year"]
            existing = by_year.get(year)
            # Prefer the standalone annual account (typeid 1) over the
            # consolidated one (typeid 2) as the canonical filing for the year.
            if existing is None or (
                existing["typeid"] != "1" and account["typeid"] == "1"
            ):
                by_year[year] = account

        filings: list[FinancialFiling] = []
        for year in sorted(by_year, reverse=True)[:years]:
            account = by_year[year]
            filings.append(
                FinancialFiling(
                    company_id=kt,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    structured_data={
                        "account_number": account["number"],
                        "account_type": account["type_label"],
                        "filing_date": account["filing_date"].isoformat()
                        if account["filing_date"]
                        else None,
                        "kennitala": kt,
                        "download": (
                            "Free via Skatturinn Ársreikningaskrá web-shop "
                            "checkout (add account number to cart, price 0)."
                        ),
                    },
                    source_url=self._detail_url(kt),
                )
            )
        return filings

    async def _fetch_detail_html(self, kt: str) -> str:
        async with build_http_client(
            base_url=self.SKATTURINN_BASE, headers=self._headers(), timeout=20.0
        ) as client:
            resp = await get_with_retry(client, f"/fyrirtaekjaskra/leit/kennitala/{kt}")
            resp.raise_for_status()
            return resp.text

    def _status_from_name(self, raw_name: str) -> str | None:
        low = raw_name.lower()
        if any(marker in low for marker in _DEREGISTERED_MARKERS):
            return "Afskráð (deregistered)"
        return None

    def _identifiers(self, detail: dict[str, Any]) -> list[RegistryIdentifier]:
        ids = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=_format_kennitala(detail["kennitala"]),
                label="Kennitala",
            )
        ]
        if detail.get("vat_number"):
            ids.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=detail["vat_number"],
                    label="VSK-númer",
                )
            )
        return ids

    def _parse_detail(self, html: str) -> dict[str, Any] | None:
        box_m = re.search(r'class="company box"(.*)', html, re.S)
        if not box_m:
            return None
        box = box_m.group(1)
        h1_m = re.search(r"<h1>(.*?)</h1>", box, re.S)
        if not h1_m:
            return None
        h1 = _text(h1_m.group(1))
        kt_m = re.search(r"\((\d{10})\)", h1)
        if not kt_m:
            return None
        kt = kt_m.group(1)

        name = re.sub(r"\(\s*\d{10}\s*\)", "", h1)
        status = self._status_from_name(name)
        name = re.sub(r"\(\s*Félag afskrá[^)]*\)", "", name).strip(" ,")

        detail: dict[str, Any] = {
            "kennitala": kt,
            "name": name,
            "status": status,
        }

        sub_m = re.search(r"Stofnað/Skráð:\s*([0-9.]+)", box)
        if sub_m:
            detail["incorporation_date"] = _parse_is_date(sub_m.group(1))

        addr_m = re.search(
            r'<table[^>]*class="nozebra"[^>]*>(.*?)</table>', box, re.S
        )
        if addr_m:
            cells = [
                _text(c)
                for c in re.findall(r"<td[^>]*>(.*?)</td>", addr_m.group(1), re.S)
            ]
            if len(cells) >= 4:
                detail["address"] = cells[1] or cells[0] or None
                detail["legal_form"] = cells[3] or None

        dir_m = re.search(r"Forráðamaður</h3>\s*<ul>(.*?)</ul>", box, re.S)
        if dir_m:
            directors: list[Director] = []
            for li in re.findall(r"<li>(.*?)</li>", dir_m.group(1), re.S):
                entry = _text(li)
                if not entry:
                    continue
                parts = entry.split(" - ", 1)
                directors.append(
                    Director(
                        name=parts[0].strip(),
                        role=parts[1].strip() if len(parts) > 1 else None,
                    )
                )
            if directors:
                detail["directors"] = directors

        isat_m = re.search(
            r"ÍSAT Atvinnugreinaflokkun</h3>\s*<ul>(.*?)</ul>", box, re.S
        )
        if isat_m:
            codes: list[str] = []
            for li in re.findall(r"<li>(.*?)</li>", isat_m.group(1), re.S):
                code = re.match(r"\s*([0-9.]+)", _text(li))
                if code:
                    codes.append(code.group(1))
            if codes:
                detail["nace_codes"] = codes

        vat_m = re.search(
            r"Virðisaukaskattsnúmer</h3>.*?<tbody>(.*?)</tbody>", box, re.S
        )
        if vat_m:
            for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", vat_m.group(1), re.S):
                cells = [
                    _text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
                ]
                cells = [c for c in cells if c]
                if len(cells) >= 2 and re.fullmatch(r"\d{1,7}", cells[0]):
                    # An active VAT registration has no deregistration date in
                    # the second column (that column would be a DD.MM.YYYY).
                    if not re.match(r"\d{1,2}\.\d{1,2}\.\d{4}", cells[1]):
                        detail["vat_number"] = f"IS{cells[0]}"
                        break

        detail["accounts"] = _parse_accounts(box)
        detail["raw"] = {
            "kennitala": kt,
            "display_name": h1,
            "legal_form": detail.get("legal_form"),
            "vat_number": detail.get("vat_number"),
            "nace_codes": detail.get("nace_codes", []),
        }
        return detail


def _results_table(html: str) -> str:
    """Return the search-results ``<table>`` markup, or empty string."""
    for table in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.S):
        if "Kennitala" in table.group(1) and "kennitala/" in table.group(1):
            return table.group(1)
    return ""


def _parse_accounts(box: str) -> list[dict[str, Any]]:
    heading = re.search(r"Gögn úr ársreikningaskrá", box)
    if not heading:
        return []
    table_start = box.find('class="annualTable"', heading.start())
    if table_start == -1:
        table_start = box.find("<table", heading.start())
    if table_start == -1:
        return []
    table_open = box.rfind("<table", heading.start(), table_start + 40)
    if table_open == -1:
        table_open = table_start
    table_end = box.find("</table>", table_open)
    block = box[table_open : table_end if table_end != -1 else len(box)]

    accounts: list[dict[str, Any]] = []
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", block, re.S):
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row.group(1), re.S)
        if len(cells) < 5:
            continue
        year_txt = _text(cells[0][1])
        if not re.fullmatch(r"\d{4}", year_txt):
            continue
        year = int(year_txt)
        filing_date = _parse_is_date(_text(cells[2][1]))
        number = _text(cells[3][1])
        type_cell_attrs, type_cell_html = cells[4]
        type_label = _text(type_cell_html)
        typeid = (re.search(r'data-typeid="(\d)"', type_cell_attrs) or [None, ""])[1]
        item = (re.search(r'data-itemid="(\d+)"', type_cell_attrs) or [None, number])[1]
        accounts.append(
            {
                "year": year,
                "filing_date": filing_date,
                "number": item or number,
                "type_label": type_label,
                "typeid": typeid,
            }
        )
    return accounts
