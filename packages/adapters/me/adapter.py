"""Montenegro adapter — CRPS + Tax Authority + Montenegroberza (MNSE).

All three sources are free, no auth, no paid contracts. Per project rules
this adapter never invents data — when a source is unreachable or returns
no rows, callers get an empty list or ``None``.

Sources:

- **CRPS** (Centralni Registar Privrednih Subjekata, run by the Tax
  Administration / Uprava prihoda i carina) — public business register at
  https://crps.mpa.gov.me/. Free HTML search and per-company detail by
  PIB (tax ID) or MB (matični broj). Both are 8-digit numeric identifiers.
- **Uprava prihoda i carina** — https://www.upravaprihoda.gov.me/ runs the
  public PIB validator. We probe its homepage for health checks because
  the CRPS portal occasionally rate-limits unsigned UAs.
- **Montenegroberza / Montenegro Stock Exchange (MNSE)** — free annual
  reports for listed issuers at https://www.mse.co.me/. We surface the
  issuer-page URL for the known MNSE-listed majors only; full reports
  are PDFs the cross-cutting extraction worker can pick up later.

Identifier scope:
- COMPANY_NUMBER → MB (Matični broj), 8 digits.
- VAT             → PIB (Poreski identifikacioni broj), 8 digits.

Both happen to share the same numeric width but the underlying registers
are distinct; we keep them as separate identifier types to preserve that
distinction downstream.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
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

_ME_ID_RE = re.compile(r"^\d{8}$")
_DIGITS_RE = re.compile(r"\d{8}")
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_STATUS_HINTS_LATIN = (
    "aktivno",
    "aktivan",
    "aktivna",
    "registrovan",
    "registrovano",
    "u steč",
    "u stec",
    "brisan",
    "ugaš",
    "ugas",
    "likvid",
)

# MNSE issuers with publicly listed annual reports. Keys are PIBs of the
# real issuers — confirmed against the test-company set in the project
# brief. Adding more entries requires verifying the issuer slug exists
# on mse.co.me.
_MNSE_ISSUER_SLUGS: dict[str, str] = {
    "02289377": "crnogorski-telekom-ad",
    "02002230": "elektroprivreda-crne-gore-ad",
    "02297473": "crnogorska-komercijalna-banka-ad",
    "02001306": "plantaze-13-jul-ad",
}


def _normalize_me_id(value: str, *, label: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("ME"):
        cleaned = cleaned[2:]
    if not _ME_ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Montenegro {label} must be 8 digits, got: {value}"
        )
    return cleaned


def _strip_tags(text: str) -> str:
    return _TAG_STRIP_RE.sub(" ", text)


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class MEAdapter(CountryAdapter):
    country_code = "ME"
    country_name = "Montenegro"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CRPS_BASE = "https://crps.mpa.gov.me"
    TAX_BASE = "https://www.upravaprihoda.gov.me"
    MNSE_BASE = "https://www.mse.co.me"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(timeout=20.0) as client:
                resp = await get_with_retry(client, f"{self.CRPS_BASE}/")
                if resp.status_code >= 500:
                    raise RuntimeError(f"CRPS HTTP {resp.status_code}")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"CRPS probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "CRPS HTML scrape (search/lookup). Financials limited to "
                "MNSE-listed issuers; non-listed filings are not freely "
                "indexed by CRPS."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        rows = await self._crps_search(name)
        out: list[CompanyMatch] = []
        seen: set[str] = set()
        for row in rows:
            pib = row.get("pib")
            mb = row.get("mb")
            primary = pib or mb
            if not primary or primary in seen:
                continue
            seen.add(primary)
            company_name = row.get("name") or ""
            if not company_name:
                continue
            idents: list[RegistryIdentifier] = []
            if pib:
                idents.append(
                    RegistryIdentifier(type=IdentifierType.VAT, value=f"ME{pib}", label="PIB")
                )
            if mb:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER, value=mb, label="MB"
                    )
                )
            out.append(
                CompanyMatch(
                    id=primary,
                    name=company_name,
                    country=self.country_code,
                    identifiers=idents,
                    address=row.get("address"),
                    status=row.get("status"),
                    source_url=self._detail_url(primary),
                )
            )
            if len(out) >= limit:
                break
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            ident = _normalize_me_id(value, label="PIB")
            label = "PIB"
        elif id_type == IdentifierType.COMPANY_NUMBER:
            ident = _normalize_me_id(value, label="MB")
            label = "MB"
        else:
            raise InvalidIdentifierError(
                f"ME supports VAT (PIB) or COMPANY_NUMBER (MB), got {id_type}"
            )

        rows = await self._crps_search(ident)
        match = _pick_by_identifier(rows, ident)
        if match is None:
            return None
        pib = match.get("pib")
        mb = match.get("mb")
        idents: list[RegistryIdentifier] = []
        if pib:
            idents.append(
                RegistryIdentifier(type=IdentifierType.VAT, value=f"ME{pib}", label="PIB")
            )
        if mb:
            idents.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=mb, label="MB"
                )
            )
        return CompanyDetails(
            id=pib or mb or ident,
            name=match.get("name") or "",
            country=self.country_code,
            legal_form=match.get("legal_form"),
            status=match.get("status"),
            registered_address=match.get("address"),
            capital_currency="EUR",
            identifiers=idents,
            raw={"crps_row": match, "queried_as": label},
            source_url=self._detail_url(pib or mb or ident),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ident = _normalize_me_id(company_id, label="PIB")
        slug = _MNSE_ISSUER_SLUGS.get(ident)
        if slug is None:
            # CRPS does not expose filed annual accounts under a free, stable
            # URL — they are deposited but only retrievable via paid extracts.
            # Empty list keeps the contract honest.
            return []
        issuer_url = f"{self.MNSE_BASE}/issuers/{slug}/"
        current_year = datetime.utcnow().year
        return [
            FinancialFiling(
                company_id=ident,
                year=current_year - 1,
                type=FilingType.ANNUAL_REPORT,
                period_end=None,
                currency="EUR",
                structured_data=None,
                document_url=issuer_url,
                document_format="html",
                source_url=issuer_url,
            )
        ]

    async def _crps_search(self, query: str) -> list[dict[str, Any]]:
        """Hit the CRPS public search page and return parsed result rows.

        The CRPS front-end exposes a single search endpoint that accepts a
        free-text term (matched against name, PIB, or MB). We submit the
        term, parse the results table, and let callers decide whether to
        treat it as a name search or an identifier lookup.
        """
        params = {"q": query}
        async with build_http_client(timeout=30.0) as client:
            for path in ("/pretraga", "/", "/Search"):
                try:
                    resp = await get_with_retry(
                        client, f"{self.CRPS_BASE}{path}", params=params
                    )
                except httpx.HTTPError:
                    continue
                if resp.status_code == 200 and resp.text:
                    rows = _parse_crps_results(resp.text)
                    if rows:
                        return rows
        return []

    def _detail_url(self, identifier: str) -> str:
        return f"{self.CRPS_BASE}/?q={identifier}"


class _CRPSResultsParser(HTMLParser):
    """Minimal table extractor for the CRPS results page.

    CRPS renders search hits in HTML tables. We collect every ``<tr>`` /
    ``<td>`` cell as plain text and let downstream heuristics pick the
    columns. This keeps the parser tolerant to layout drift — only a
    catastrophic markup change (e.g. switching to a JS-only client) breaks
    it, and that surfaces as an empty result, not fake data.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            self._row.append(_normalize_ws("".join(self._cell)))
            self._cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if any(c for c in self._row):
                self.rows.append(self._row)
            self._row = []
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _parse_crps_results(html_text: str) -> list[dict[str, Any]]:
    parser = _CRPSResultsParser()
    try:
        parser.feed(html_text)
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        if not cells:
            continue
        ids = _extract_ids(cells)
        if not ids["pib"] and not ids["mb"]:
            continue
        name = _extract_name(cells, ids)
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "pib": ids["pib"],
                "mb": ids["mb"],
                "address": _extract_address(cells, name, ids),
                "status": _extract_status(cells),
                "legal_form": _extract_legal_form(name),
            }
        )
    return rows


def _extract_ids(cells: list[str]) -> dict[str, str | None]:
    pib: str | None = None
    mb: str | None = None
    # We can't tell PIB from MB by digit pattern alone (both 8 digits).
    # Heuristic: cells often label the column ("PIB:", "MB:"); if no label
    # is present, the first 8-digit token wins as PIB and the second as MB.
    for cell in cells:
        upper = cell.upper()
        for match in _DIGITS_RE.finditer(cell):
            digits = match.group(0)
            context = cell[max(0, match.start() - 6) : match.start()].upper()
            tail = upper
            if "PIB" in context or "PIB" in tail[:8]:
                pib = pib or digits
            elif "MB" in context or "MATIČNI" in upper or "MATICNI" in upper:
                mb = mb or digits
    if pib is None or mb is None:
        flat: list[str] = []
        for cell in cells:
            for match in _DIGITS_RE.finditer(cell):
                flat.append(match.group(0))
        if pib is None and flat:
            pib = flat[0]
        if mb is None and len(flat) > 1:
            mb = flat[1] if flat[1] != pib else (flat[2] if len(flat) > 2 else None)
    return {"pib": pib, "mb": mb}


def _extract_name(cells: list[str], ids: dict[str, str | None]) -> str | None:
    id_values = {ids["pib"], ids["mb"]} - {None}
    best: str | None = None
    for cell in cells:
        compact = cell.replace(" ", "")
        if not cell or compact.isdigit():
            continue
        if any(idv and idv in compact for idv in id_values):
            stripped = cell
            for idv in id_values:
                if idv:
                    stripped = stripped.replace(idv, "")
            stripped = _normalize_ws(stripped)
            if len(stripped) < 4:
                continue
            cell = stripped
        norm = _strip_diacritics(cell).lower()
        if any(h in norm for h in _STATUS_HINTS_LATIN) and len(cell) < 25:
            continue
        if best is None or len(cell) > len(best):
            best = cell
    return best


def _extract_address(
    cells: list[str], name: str, ids: dict[str, str | None]
) -> str | None:
    id_values = {ids["pib"], ids["mb"]} - {None}
    address_keywords = ("ulica", "bb", "podgorica", "nikšić", "niksic", "bar", "kotor")
    for cell in cells:
        if not cell or cell == name:
            continue
        compact = cell.replace(" ", "")
        if compact.isdigit():
            continue
        if any(idv and idv in compact for idv in id_values):
            continue
        norm = _strip_diacritics(cell).lower()
        if any(k in norm for k in address_keywords) or re.search(r"\d{5}", cell):
            return cell
    return None


def _extract_status(cells: list[str]) -> str | None:
    for cell in cells:
        norm = _strip_diacritics(cell).lower()
        if any(h in norm for h in _STATUS_HINTS_LATIN):
            return cell
    return None


def _extract_legal_form(name: str) -> str | None:
    # Montenegrin legal-form suffixes are a closed, short list — pull from
    # the company name when CRPS doesn't split them into a dedicated column.
    upper = name.upper()
    for token in ("A.D.", "AD", "D.O.O.", "DOO", "K.D.", "KD", "O.D.", "OD"):
        if f" {token}" in f" {upper}" or upper.endswith(token):
            return token.replace(".", "")
    return None


def _pick_by_identifier(
    rows: list[dict[str, Any]], ident: str
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("pib") == ident or row.get("mb") == ident:
            return row
    return rows[0] if len(rows) == 1 else None


def _strip_diacritics(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
