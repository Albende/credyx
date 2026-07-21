"""Montenegro adapter — Tax Administration white list + Montenegroberza (MNSE).

Both sources are free, need no API key, and no paid contract. Per project
rules this adapter never invents data — when a source has no record for a
company, callers get an empty list or ``None``.

Sources:

- **Bijela lista poreskih obveznika** (Tax Administration "white list" of
  compliant taxpayers), published as open data on the national portal
  https://data.gov.me/. A single XLSX maps ``PIB`` (tax id) → registered
  company name for every major Montenegrin taxpayer. We resolve the live
  download URL through the CKAN API and cache the parsed table in-process.
  This is the backbone for name search and identifier lookup.
- **Montenegroberza / Montenegro Stock Exchange (MNSE)** —
  https://www.mnse.me/. Free issuer profiles (matični broj, registered
  address, NACE activity code, ISIN) and — crucially — the actual filed
  financial and audit reports as downloadable PDFs, per listed issuer.

The former CRPS web register (``crps.me`` / ``crps.mpa.gov.me``) is dead —
the domains are parked, and the replacement portal ``irms.tax.gov.me``
answers ``503`` to every off-Montenegro request, so neither is usable from
here. See ``docs/countries/me.md`` for the source audit.

Identifier scope:
- VAT             → PIB (Poreski identifikacioni broj), 8 digits.
- COMPANY_NUMBER  → MB (Matični broj), 8 digits.

Montenegrin companies commonly share the same numeric value for PIB and MB,
but the registers are distinct so we keep both identifier types.
"""
from __future__ import annotations

import asyncio
import html
import io
import re
import unicodedata
import zipfile
from datetime import datetime
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

# mnse.me serves a stripped WAP page to non-browser user-agents; the full
# desktop site (with issuer profiles and filing PDFs) needs a browser UA.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_ME_ID_RE = re.compile(r"^\d{8}$")
_PIB_TOKEN_RE = re.compile(r"^\d{8}$")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_LEGAL_FORM_TOKENS = ("A.D.", "AD", "D.O.O.", "DOO", "K.D.", "KD", "O.D.", "OD")
_STOPWORDS = {
    "AD",
    "DOO",
    "KD",
    "OD",
    "CRNE",
    "GORE",
    "PODGORICA",
    "NIKSIC",
    "DRUSTVO",
    "SA",
    "OGRANICENOM",
    "ODGOVORNOSCU",
    "PREDUZECE",
    "KOMPANIJA",
    "AKCIONARSKO",
    "AKCIONARSKO DRUSTVO",
    "AND",
    "THE",
}

_CKAN_PACKAGE = "bijela-lista-poreskih-obveznika"


def _normalize_me_id(value: str, *, label: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("ME"):
        cleaned = cleaned[2:]
    if not _ME_ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Montenegro {label} must be 8 digits, got: {value}"
        )
    return cleaned


def _strip_diacritics(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm_name(name: str) -> str:
    return _normalize_ws(_strip_diacritics(name).upper())


def _name_tokens(name: str) -> list[str]:
    """Distinctive uppercase, diacritic-free tokens for fuzzy matching."""
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", _strip_diacritics(name).upper())
    tokens = [t for t in cleaned.split() if len(t) >= 3 and t not in _STOPWORDS]
    tokens.sort(key=len, reverse=True)
    return tokens


def _extract_legal_form(name: str) -> str | None:
    upper = name.upper()
    for token in _LEGAL_FORM_TOKENS:
        if f" {token}" in f" {upper}" or upper.endswith(token):
            return token.replace(".", "")
    return None


_BIJELA_CACHE: dict[str, str] | None = None
_BIJELA_LOCK = asyncio.Lock()


def _parse_bijela_xlsx(content: bytes) -> dict[str, str]:
    """Extract PIB → name from the Tax Administration white-list workbook.

    The sheet materializes a million empty rows (>80 MB) but every value is
    a shared string, so we read only ``sharedStrings.xml`` (tens of KB) and
    pair each 8-digit PIB with the string that follows it.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        raw = archive.read("xl/sharedStrings.xml").decode("utf-8", "replace")
    strings = [
        html.unescape(m)
        for m in re.findall(r"<si>(?:<t[^>]*>(.*?)</t>|)</si>", raw, re.S)
    ]
    table: dict[str, str] = {}
    for i, value in enumerate(strings):
        if _PIB_TOKEN_RE.match(value) and i + 1 < len(strings):
            name = _normalize_ws(strings[i + 1])
            if name:
                table.setdefault(value, name)
    return table


async def _load_bijela() -> dict[str, str]:
    global _BIJELA_CACHE
    if _BIJELA_CACHE is not None:
        return _BIJELA_CACHE
    async with _BIJELA_LOCK:
        if _BIJELA_CACHE is not None:
            return _BIJELA_CACHE
        headers = {"User-Agent": _BROWSER_UA}
        async with build_http_client(timeout=90.0, headers=headers) as client:
            meta = await get_with_retry(
                client,
                "https://data.gov.me/api/3/action/package_show",
                params={"id": _CKAN_PACKAGE},
            )
            url = _pick_xlsx_url(meta.json())
            resp = await get_with_retry(client, url)
            resp.raise_for_status()
            _BIJELA_CACHE = _parse_bijela_xlsx(resp.content)
    return _BIJELA_CACHE


def _pick_xlsx_url(package_payload: dict[str, Any]) -> str:
    resources = package_payload.get("result", {}).get("resources", [])
    for res in resources:
        if (res.get("format") or "").upper() == "XLSX" and res.get("url"):
            return res["url"]
    for res in resources:
        if (res.get("url") or "").lower().endswith(".xlsx"):
            return res["url"]
    raise httpx.HTTPError("No XLSX resource on Bijela lista dataset")


class MEAdapter(CountryAdapter):
    country_code = "ME"
    country_name = "Montenegro"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    MNSE_BASE = "https://www.mnse.me"
    DATA_BASE = "https://data.gov.me"

    async def health_check(self) -> AdapterHealth:
        notes = []
        ok = True
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client, f"{self.MNSE_BASE}/symbols.asp", params={"term": "banka"}
                )
                if resp.status_code != 200 or not resp.text.strip().startswith("["):
                    ok = False
                    notes.append(f"MNSE search HTTP {resp.status_code}")
        except Exception as exc:
            ok = False
            notes.append(f"MNSE probe failed: {str(exc)[:120]}")
        try:
            await _load_bijela()
        except Exception as exc:
            ok = False
            notes.append(f"Bijela lista load failed: {str(exc)[:120]}")
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.ERROR,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "; ".join(notes)
                if notes
                else (
                    "Search/lookup via Tax Administration white list "
                    "(data.gov.me); financials via MNSE issuer filings. "
                    "Coverage is limited to white-listed and MNSE-listed "
                    "companies — the CRPS/IRMS web register is unreachable."
                )
            ),
        )

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(timeout=30.0, headers={"User-Agent": _BROWSER_UA})

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = _norm_name(name)
        if len(query) < 2:
            return []
        table = await _load_bijela()
        out: list[CompanyMatch] = []
        seen_pib: set[str] = set()
        seen_name: set[str] = set()

        for pib, company_name in table.items():
            if query in _norm_name(company_name):
                seen_pib.add(pib)
                seen_name.add(_norm_name(company_name))
                out.append(
                    CompanyMatch(
                        id=pib,
                        name=company_name,
                        country=self.country_code,
                        identifiers=[
                            RegistryIdentifier(
                                type=IdentifierType.VAT, value=f"ME{pib}", label="PIB"
                            )
                        ],
                        status="Aktivan",
                        source_url=f"{self.DATA_BASE}/dataset/{_CKAN_PACKAGE}",
                    )
                )
                if len(out) >= limit:
                    return out

        async with self._client() as client:
            issuers = await self._mnse_group_issuers(client, name)
            for issuer in issuers:
                if len(out) >= limit:
                    break
                detail = await self._mnse_detail(client, issuer["id"])
                if detail is None:
                    continue
                mb = detail.get("mb")
                display_name = detail.get("name") or issuer["issuer_desc"]
                if _norm_name(display_name) in seen_name:
                    continue
                if mb and mb in seen_pib:
                    continue
                idents: list[RegistryIdentifier] = []
                if mb:
                    idents.append(
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER, value=mb, label="MB"
                        )
                    )
                    if mb in table:
                        idents.insert(
                            0,
                            RegistryIdentifier(
                                type=IdentifierType.VAT, value=f"ME{mb}", label="PIB"
                            ),
                        )
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.OTHER,
                        value=issuer["label"],
                        label="MNSE symbol",
                    )
                )
                out.append(
                    CompanyMatch(
                        id=mb or issuer["label"],
                        name=display_name,
                        country=self.country_code,
                        identifiers=idents,
                        address=detail.get("address"),
                        status="Listed (MNSE)",
                        source_url=self._issuer_url(issuer["id"]),
                    )
                )
        return out[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            ident = _normalize_me_id(value, label="PIB")
        elif id_type == IdentifierType.COMPANY_NUMBER:
            ident = _normalize_me_id(value, label="MB")
        else:
            raise InvalidIdentifierError(
                f"ME supports VAT (PIB) or COMPANY_NUMBER (MB), got {id_type}"
            )

        table = await _load_bijela()
        name = table.get(ident)
        if name is None:
            return None

        idents = [
            RegistryIdentifier(type=IdentifierType.VAT, value=f"ME{ident}", label="PIB")
        ]
        raw: dict[str, Any] = {"source": "bijela_lista", "pib": ident}
        address: str | None = None
        nace: list[str] = []

        async with self._client() as client:
            issuer = await self._resolve_issuer(client, name)
            if issuer is not None:
                detail = await self._mnse_detail(client, issuer["id"])
                if detail is not None:
                    raw["mnse"] = detail
                    address = detail.get("address")
                    mb = detail.get("mb")
                    if mb:
                        idents.append(
                            RegistryIdentifier(
                                type=IdentifierType.COMPANY_NUMBER,
                                value=mb,
                                label="MB",
                            )
                        )
                    if detail.get("isin"):
                        idents.append(
                            RegistryIdentifier(
                                type=IdentifierType.OTHER,
                                value=detail["isin"],
                                label="ISIN",
                            )
                        )
                    idents.append(
                        RegistryIdentifier(
                            type=IdentifierType.OTHER,
                            value=issuer["label"],
                            label="MNSE symbol",
                        )
                    )
                    if detail.get("nace"):
                        nace = [detail["nace"]]

        return CompanyDetails(
            id=ident,
            name=name,
            country=self.country_code,
            legal_form=_extract_legal_form(name),
            status="Aktivan",
            registered_address=address,
            capital_currency="EUR",
            nace_codes=nace,
            identifiers=idents,
            raw=raw,
            source_url=f"{self.DATA_BASE}/dataset/{_CKAN_PACKAGE}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ident = _normalize_me_id(company_id, label="PIB")
        table = await _load_bijela()
        name = table.get(ident)
        if name is None:
            return []

        async with self._client() as client:
            issuer = await self._resolve_issuer(client, name)
            if issuer is None:
                return []
            resp = await get_with_retry(client, self._issuer_url(issuer["id"]))
            docs = _parse_financial_docs(resp.text)

        source_url = self._issuer_url(issuer["id"])
        filings: list[FinancialFiling] = []
        for doc in docs:
            filings.append(
                FinancialFiling(
                    company_id=ident,
                    year=doc["year"],
                    type=doc["type"],
                    currency="EUR",
                    document_url=f"{self.MNSE_BASE}{doc['href']}",
                    document_format=doc["format"],
                    source_url=source_url,
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        if filings:
            cutoff = filings[0].year - years + 1
            filings = [f for f in filings if f.year >= cutoff]
        return filings

    async def _mnse_group_issuers(
        self, client: httpx.AsyncClient, term: str
    ) -> list[dict[str, str]]:
        rows = await self._mnse_search(client, term)
        grouped: dict[str, dict[str, str]] = {}
        for row in rows:
            desc = row.get("issuer_desc") or ""
            label = row.get("label") or ""
            sid = row.get("id") or ""
            if not desc or not sid:
                continue
            current = grouped.get(desc)
            if current is None or _base_symbol_rank(label) < _base_symbol_rank(
                current["label"]
            ):
                grouped[desc] = {"label": label, "id": sid, "issuer_desc": desc}
        return list(grouped.values())

    async def _resolve_issuer(
        self, client: httpx.AsyncClient, name: str
    ) -> dict[str, str] | None:
        tokens = _name_tokens(name)
        if not tokens:
            return None
        target = _norm_name(name)
        for term in tokens[:2]:
            issuers = await self._mnse_group_issuers(client, term)
            best: dict[str, str] | None = None
            best_score = 0
            for issuer in issuers:
                desc = _norm_name(issuer["issuer_desc"])
                score = sum(1 for tok in tokens if tok in desc)
                if term not in desc:
                    continue
                if score > best_score or (
                    score == best_score and desc == target
                ):
                    best, best_score = issuer, score
            if best is not None and best_score >= 1:
                return best
        return None

    async def _mnse_search(
        self, client: httpx.AsyncClient, term: str
    ) -> list[dict[str, Any]]:
        resp = await get_with_retry(
            client, f"{self.MNSE_BASE}/symbols.asp", params={"term": term}
        )
        if resp.status_code != 200:
            return []
        body = resp.text.strip()
        if not body.startswith("["):
            return []
        import json

        try:
            return json.loads(body)
        except ValueError:
            return []

    async def _mnse_detail(
        self, client: httpx.AsyncClient, stock_id: str
    ) -> dict[str, Any] | None:
        resp = await get_with_retry(client, self._issuer_url(stock_id))
        if resp.status_code != 200:
            return None
        return _parse_issuer_detail(resp.text)

    def _issuer_url(self, stock_id: str) -> str:
        return f"{self.MNSE_BASE}/code/navigate.asp?Id=14&stockId={stock_id}"


def _base_symbol_rank(label: str) -> tuple[int, int]:
    """Lower rank == more likely the issuer's primary equity symbol."""
    has_suffix = 1 if "-" in label else 0
    return (has_suffix, len(label))


def _parse_issuer_detail(html_text: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    header = re.search(r'td_header_row[^>]*>([^<]+)</td>', html_text)
    name = _normalize_ws(header.group(1)) if header else ""
    if name and name.upper() not in ("SIMBOL", "SYMBOL"):
        info["name"] = name
    for label, val in re.findall(
        r'td_color2_\d+">([^<]+)</td>\s*<td class="td_color1_\d+[^"]*">([^<]*)</td>',
        html_text,
    ):
        label_n = _strip_diacritics(label).strip().lower()
        value = _normalize_ws(html.unescape(val))
        if not value:
            continue
        if label_n.startswith("adresa"):
            info["address"] = value
        elif label_n.startswith("maticni"):
            info["mb"] = value.zfill(8)
        elif label_n.startswith("sifra djelatnosti"):
            info["nace"] = value
    isin = re.search(r"ISIN\s*</td>\s*<td[^>]*>([A-Z]{2}[A-Z0-9]{9,10})", html_text)
    if isin:
        info["isin"] = isin.group(1)
    return info


def _parse_financial_docs(html_text: str) -> list[dict[str, Any]]:
    start = html_text.find("Finansijski i revizorski izvje")
    if start == -1:
        return []
    end = html_text.find("<h1>", start + 5)
    section = html_text[start : end if end != -1 else start + 8000]
    docs: list[dict[str, Any]] = []
    seen: set[tuple[int, FilingType]] = set()
    for href, inner in re.findall(
        r'href="(/upload/[^"]+)"[^>]*>(.*?)</a>', section, re.S
    ):
        text = _normalize_ws(re.sub(r"<[^>]+>", " ", html.unescape(inner)))
        years = _YEAR_RE.findall(text)
        if not years:
            continue
        year = max(int(y) for y in years)
        filing_type = _classify_filing(text)
        key = (year, filing_type)
        if key in seen:
            continue
        seen.add(key)
        ext = href.rsplit(".", 1)[-1].lower() if "." in href else None
        docs.append(
            {
                "href": href,
                "year": year,
                "type": filing_type,
                "format": ext,
                "description": text,
            }
        )
    return docs


def _classify_filing(text: str) -> FilingType:
    lowered = _strip_diacritics(text).lower()
    if "revizor" in lowered:
        return FilingType.AUDIT_REPORT
    if "godisnji izvjestaj" in lowered:
        return FilingType.ANNUAL_REPORT
    return FilingType.BALANCE_SHEET
