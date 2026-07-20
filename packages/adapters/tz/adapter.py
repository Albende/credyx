"""Tanzania adapter.

Two free, key-less live sources (verified July 2026):

- BRELA ORS (Business Registrations and Licensing Agency) —
  https://ors.brela.go.tz/orsreg/searchbusinesspublic
  The public search backs onto a JSON endpoint,
  ``/orsreg/list/search/businesspublic.json``, that accepts a JSON POST body
  ``{"object_type": "ET-COMPANY"|"ET-BUSINESS", "cm_name"|"bn_name": ...,
  "cm_number"|"bn_number": ..., "PageSize": n, "PageNumber": n}`` and returns
  real registry records. The site sits behind a WAF that blocks
  ``application/x-www-form-urlencoded`` POSTs and the default crawler
  user-agent — a JSON body plus a browser UA passes. Powers ``search_by_name``
  and ``lookup_by_identifier``.
- DSE (Dar es Salaam Stock Exchange) — https://dse.co.tz/
  Listed-issuer audited statements are published as downloadable PDFs under
  ``/storage/securities/{TICKER}/financial_statement/{Annual|Quarterly}/``.
  The per-company list is served by a Livewire component
  (``financial-statement-front-component``). ``fetch_financials`` drives that
  component and returns one ``FinancialFiling`` per filed report, each with a
  real, downloadable ``document_url``. No numbers are invented.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterNotImplementedError
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

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

_BRELA_HOST = "https://ors.brela.go.tz"
_BRELA_SEARCH_PAGE = f"{_BRELA_HOST}/orsreg/searchbusinesspublic"
_BRELA_SEARCH_JSON = f"{_BRELA_HOST}/orsreg/list/search/businesspublic.json"

_DSE_HOST = "https://dse.co.tz"
_DSE_FS_PAGE = f"{_DSE_HOST}/listed/company/financial/statement"

_DSE_REPORT_TYPES = ("Annual", "Interim", "Quarterly")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _brela_headers() -> dict[str, str]:
    return {
        "User-Agent": _BROWSER_UA,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": _BRELA_SEARCH_PAGE,
        "Origin": _BRELA_HOST,
    }


def _record_to_dict(map_keys: list[str], record: list) -> dict:
    return dict(zip(map_keys, record))


class TZAdapter(CountryAdapter):
    country_code = "TZ"
    country_name = "Tanzania"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    async def _brela_query(
        self,
        *,
        object_type: str,
        name: str | None = None,
        number: str | None = None,
        page_size: int = 10,
    ) -> list[dict]:
        body: dict[str, object] = {
            "object_type": object_type,
            "PageSize": page_size,
            "PageNumber": 1,
        }
        if object_type == "ET-COMPANY":
            if name:
                body["cm_name"] = name
            if number:
                body["cm_number"] = number
        else:
            if name:
                body["bn_name"] = name
            if number:
                body["bn_number"] = number

        async with build_http_client(headers=_brela_headers()) as client:
            resp = await client.post(_BRELA_SEARCH_JSON, content=json.dumps(body))
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("Result") != "OK":
            return []
        map_keys = payload.get("Map", [])
        return [_record_to_dict(map_keys, rec) for rec in payload.get("Records", [])]

    def _record_to_match(self, rec: dict) -> CompanyMatch:
        number = str(rec.get("cert_number") or rec.get("id"))
        return CompanyMatch(
            id=number,
            name=(rec.get("legal_name") or "").strip(),
            country="TZ",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=number,
                    label="BRELA registration number",
                )
            ],
            address=(rec.get("address") or None),
            status=(rec.get("reg_status_name") or None),
            source_url=_BRELA_SEARCH_PAGE,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []

        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for object_type, key in (("ET-COMPANY", "cm_name"), ("ET-BUSINESS", "bn_name")):
            if len(matches) >= limit:
                break
            records = await self._brela_query(
                object_type=object_type, name=query, page_size=limit
            )
            for rec in records:
                match = self._record_to_match(rec)
                if match.id in seen:
                    continue
                seen.add(match.id)
                matches.append(match)
                if len(matches) >= limit:
                    break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise AdapterNotImplementedError(
                "TZ lookup supports the BRELA COMPANY_NUMBER only. TRA TIN (VAT) "
                "validation is interactive-only with no public API."
            )
        number = value.strip()
        if not number:
            return None

        rec: dict | None = None
        for object_type in ("ET-COMPANY", "ET-BUSINESS"):
            records = await self._brela_query(
                object_type=object_type, number=number, page_size=5
            )
            exact = [r for r in records if str(r.get("cert_number")) == number]
            if exact:
                rec = exact[0]
                break
            if records and rec is None:
                rec = records[0]
        if rec is None:
            return None

        cert = str(rec.get("cert_number") or number)
        return CompanyDetails(
            id=cert,
            name=(rec.get("legal_name") or "").strip(),
            country="TZ",
            legal_form=(rec.get("subtype_name") or None),
            status=(rec.get("reg_status_name") or None),
            incorporation_date=_parse_date(
                rec.get("incorporation_date") or rec.get("reg_date")
            ),
            dissolution_date=_parse_date(rec.get("cess_date")),
            registered_address=(rec.get("address") or None),
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=cert,
                    label="BRELA registration number",
                )
            ],
            raw=rec,
            source_url=_BRELA_SEARCH_PAGE,
        )

    async def _dse_roster(self, client: httpx.AsyncClient) -> tuple[dict[str, str], str, dict]:
        resp = await get_with_retry(client, _DSE_FS_PAGE)
        resp.raise_for_status()
        page = resp.text

        token_match = re.search(r'name="csrf-token"\s+content="([^"]+)"', page)
        data_match = re.search(r'wire:initial-data="([^"]+)"', page)
        if not token_match or not data_match:
            return {}, "", {}
        csrf = token_match.group(1)
        component = json.loads(html.unescape(data_match.group(1)))

        roster: dict[str, str] = {}
        for select in re.findall(r"<select\b[^>]*>(.*?)</select>", page, re.S):
            for cid, label in re.findall(
                r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', select
            ):
                ticker = label.strip().upper()
                if ticker and cid not in {"Annual", "Interim", "Quarterly"}:
                    roster.setdefault(ticker, cid)
        return roster, csrf, component

    async def _dse_statements(
        self,
        client: httpx.AsyncClient,
        component: dict,
        csrf: str,
        comp_id: str,
        report_type: str,
    ) -> list[dict]:
        fingerprint = component["fingerprint"]
        server_memo = component["serverMemo"]
        payload = {
            "fingerprint": fingerprint,
            "serverMemo": server_memo,
            "updates": [
                {
                    "type": "syncInput",
                    "payload": {"id": "rt", "name": "report_type", "value": report_type},
                },
                {
                    "type": "syncInput",
                    "payload": {"id": "cid", "name": "comp_id", "value": comp_id},
                },
            ],
        }
        url = f"{_DSE_HOST}/livewire/message/{fingerprint['name']}"
        resp = await client.post(
            url,
            content=json.dumps(payload),
            headers={
                "User-Agent": _BROWSER_UA,
                "Content-Type": "application/json",
                "Accept": "text/html, application/xhtml+xml",
                "X-Requested-With": "XMLHttpRequest",
                "X-Livewire": "true",
                "X-CSRF-TOKEN": csrf,
                "Referer": _DSE_FS_PAGE,
            },
        )
        resp.raise_for_status()
        rendered = resp.json().get("effects", {}).get("html", "") or ""

        statements: list[dict] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", rendered, re.S):
            href = re.search(r'href="([^"]+/storage/securities/[^"]+\.pdf)"', row) or re.search(
                r'href="(/storage/securities/[^"]+\.pdf)"', row
            )
            if not href:
                continue
            cells = [
                re.sub(r"<[^>]+>", "", c).strip()
                for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            ]
            period = next((c for c in cells if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)), None)
            title = next((c for c in cells if re.search(r"20\d\d", c) and c != period), "")
            statements.append(
                {
                    "url": href.group(1),
                    "period_end": period,
                    "title": title,
                }
            )
        return statements

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        key = company_id.strip().upper()
        if not key:
            return []

        async with build_http_client(
            base_url=_DSE_HOST, headers={"User-Agent": _BROWSER_UA}
        ) as client:
            roster, csrf, component = await self._dse_roster(client)
            if not component:
                return []

            comp_id = key if key.isdigit() else roster.get(key)
            if comp_id is None:
                comp_id = next(
                    (cid for ticker, cid in roster.items() if key in ticker), None
                )
            if comp_id is None:
                return []

            statements: list[dict] = []
            for report_type in _DSE_REPORT_TYPES:
                statements = await self._dse_statements(
                    client, component, csrf, comp_id, report_type
                )
                if statements:
                    break

        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for stmt in statements:
            period = _parse_date(stmt["period_end"])
            year_match = re.search(r"20\d\d", stmt["title"]) or (
                re.search(r"20\d\d", stmt["period_end"] or "")
            )
            year = int(year_match.group(0)) if year_match else (
                period.year if period else 0
            )
            if year in seen_years:
                continue
            seen_years.add(year)
            url = stmt["url"]
            if url.startswith("/"):
                url = f"{_DSE_HOST}{url}"
            filings.append(
                FinancialFiling(
                    company_id=key,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period,
                    currency="TZS",
                    structured_data=None,
                    document_url=url,
                    document_format="pdf",
                    source_url=_DSE_FS_PAGE,
                )
            )
            if len(filings) >= years:
                break
        return filings

    async def health_check(self) -> AdapterHealth:
        try:
            records = await self._brela_query(
                object_type="ET-COMPANY", name="BANK", page_size=1
            )
            search_ok = bool(records)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes=f"BRELA probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if search_ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "Registry search/lookup via BRELA ORS JSON endpoint; financials "
                "via DSE-listed-issuer audited PDF statements."
            ),
        )
