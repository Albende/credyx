"""Czech Republic adapter.

Registry data (search + lookup) comes from ARES — the free public REST API
at https://ares.gov.cz/ekonomicke-subjekty/. Identifier: IČO, 8 digits, no auth.

Financial filings come from the Sbírka listin (collection of documents) of the
public register at or.justice.cz. Each company's filed financial statements
(účetní závěrka) and annual reports (výroční zpráva) are public downloads
(PDF or iXBRL/ESEF xhtml). No auth, no bot wall.
"""
from __future__ import annotations

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

_ICO_RE = re.compile(r"^\d{8}$")

_JUSTICE_ORIGIN = "https://or.justice.cz"
_JUSTICE_UI = f"{_JUSTICE_ORIGIN}/ias/ui"

_SUBJEKT_RE = re.compile(r"subjektId=(\d+)")
_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_DOKUMENT_RE = re.compile(r"vypis-sl-detail\?dokument=(\d+)")
_SPIS_RE = re.compile(r"vypis-sl-detail\?dokument=\d+&(?:amp;)?subjektId=\d+&(?:amp;)?spis=(\d+)")
_SYMBOL_RE = re.compile(r'<span class="symbol">([^<]+)</span>')
_YEAR_RE = re.compile(r"\[(\d{4})\]")
_DOWNLOAD_RE = re.compile(
    r'href="(/ias/content/download\?id=[0-9a-fA-F]+)"[^>]*>\s*<span>([^<]+)</span>'
)
_FILENAME_DATE_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})-")


class CZAdapter(CountryAdapter):
    country_code = "CZ"
    country_name = "Czech Republic"
    identifier_types = [IdentifierType.ICO]
    primary_identifier = IdentifierType.ICO
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                # Probe a known IČO instead of name search to avoid the POST/body
                # requirement in a health check.
                resp = await get_with_retry(client, "/ekonomicke-subjekty/45274649")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code, name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            notes="Registry via ARES; filings via Sbírka listin (or.justice.cz).",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # ARES `vyhledat` is a POST endpoint with a JSON body — sending it as
        # a query-string GET returns 400.
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await client.post(
                "/ekonomicke-subjekty/vyhledat",
                json={"obchodniJmeno": name, "pocet": limit, "start": 0},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        out: list[CompanyMatch] = []
        for item in (data.get("ekonomickeSubjekty") or [])[:limit]:
            ico = item.get("ico")
            if not ico:
                continue
            out.append(
                CompanyMatch(
                    id=ico,
                    name=item.get("obchodniJmeno", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.ICO, value=ico, label="IČO"),
                    ],
                    address=_address(item.get("sidlo") or {}),
                    status=("active" if not item.get("datumZaniku") else "ceased"),
                    source_url=f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.ICO:
            raise InvalidIdentifierError("CZ only supports IČO")
        ico = value.strip().replace(" ", "").zfill(8)
        if not _ICO_RE.match(ico):
            raise InvalidIdentifierError(f"IČO must be 8 digits: {value}")
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, f"/ekonomicke-subjekty/{ico}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        pravni_forma = data.get("pravniForma")
        if isinstance(pravni_forma, dict):
            legal_form = pravni_forma.get("nazev")
        else:
            legal_form = str(pravni_forma) if pravni_forma else None
        return CompanyDetails(
            id=ico,
            name=data.get("obchodniJmeno", ""),
            country="CZ",
            legal_form=legal_form,
            status=("active" if not data.get("datumZaniku") else "ceased"),
            incorporation_date=_parse_date(data.get("datumVzniku")),
            dissolution_date=_parse_date(data.get("datumZaniku")),
            registered_address=_address(data.get("sidlo") or {}),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.ICO, value=ico, label="IČO"),
                *(
                    [RegistryIdentifier(type=IdentifierType.VAT, value=data["dic"], label="DIČ")]
                    if data.get("dic") else []
                ),
            ],
            raw=data,
            source_url=f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ico = company_id.strip().replace(" ", "").zfill(8)
        if not _ICO_RE.match(ico):
            raise InvalidIdentifierError(f"IČO must be 8 digits: {company_id}")

        async with build_http_client() as client:
            subjekt_id = await self._resolve_subjekt_id(client, ico)
            if subjekt_id is None:
                return []

            resp = await get_with_retry(
                client, f"{_JUSTICE_UI}/vypis-sl-firma?subjektId={subjekt_id}"
            )
            resp.raise_for_status()
            candidates = _parse_document_rows(resp.text)
            if not candidates:
                return []

            wanted_years = sorted({c["year"] for c in candidates}, reverse=True)[:years]
            selected: list[dict[str, Any]] = []
            seen: set[tuple[int, FilingType]] = set()
            for cand in candidates:
                if cand["year"] not in wanted_years:
                    continue
                key = (cand["year"], cand["type"])
                if key in seen:
                    continue
                seen.add(key)
                selected.append(cand)

            filings: list[FinancialFiling] = []
            for cand in selected:
                detail_url = (
                    f"{_JUSTICE_UI}/vypis-sl-detail?dokument={cand['dokument']}"
                    f"&subjektId={subjekt_id}&spis={cand['spis']}"
                )
                detail = await get_with_retry(client, detail_url)
                if detail.status_code != 200:
                    continue
                link = _DOWNLOAD_RE.search(detail.text)
                if not link:
                    continue
                document_url = _JUSTICE_ORIGIN + link.group(1)
                filename = link.group(2).strip()
                filings.append(
                    FinancialFiling(
                        company_id=ico,
                        year=cand["year"],
                        type=cand["type"],
                        period_end=_period_end(filename, cand["year"]),
                        currency="CZK",
                        document_url=document_url,
                        document_format=_doc_format(filename),
                        source_url=detail_url,
                    )
                )
            return filings

    async def _resolve_subjekt_id(
        self, client: httpx.AsyncClient, ico: str
    ) -> int | None:
        resp = await get_with_retry(
            client, f"{_JUSTICE_UI}/rejstrik-$firma?ico={ico}"
        )
        resp.raise_for_status()
        match = _SUBJEKT_RE.search(resp.text)
        return int(match.group(1)) if match else None


def _address(s: dict[str, Any]) -> str | None:
    parts = [
        s.get("nazevUlice"),
        s.get("cisloDomovni"),
        s.get("nazevObce"),
        s.get("psc"),
    ]
    parts = [str(p) for p in parts if p]
    return " ".join(parts) or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _classify(symbols: str) -> FilingType | None:
    if "výroční zpráva" in symbols:
        return FilingType.ANNUAL_REPORT
    if "účetní závěrka" in symbols:
        return FilingType.BALANCE_SHEET
    if "zpráva auditora" in symbols or "zpráva o auditu" in symbols:
        return FilingType.AUDIT_REPORT
    return None


def _parse_document_rows(html: str) -> list[dict[str, Any]]:
    """Extract financial-filing rows (newest first) from a Sbírka listin listing."""
    out: list[dict[str, Any]] = []
    for row in _ROW_RE.findall(html):
        doc_match = _DOKUMENT_RE.search(row)
        if not doc_match:
            continue
        symbols = " ".join(_SYMBOL_RE.findall(row))
        filing_type = _classify(symbols)
        if filing_type is None:
            continue
        years = [int(y) for y in _YEAR_RE.findall(symbols)]
        if not years:
            continue
        spis_match = _SPIS_RE.search(row)
        out.append(
            {
                "dokument": doc_match.group(1),
                "spis": spis_match.group(1) if spis_match else None,
                "type": filing_type,
                "year": max(years),
            }
        )
    return out


def _period_end(filename: str, year: int) -> date:
    match = _FILENAME_DATE_RE.search(filename)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return date(year, 12, 31)


def _doc_format(filename: str) -> str | None:
    _, _, ext = filename.rpartition(".")
    return ext.lower() if ext and ext != filename else None
