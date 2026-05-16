"""Canada adapter — Corporations Canada (federal) + SEDAR+ (listed financials).

Two free public sources, no API key required:

- **Corporations Canada** (Innovation, Science and Economic Development Canada)
  hosts the federal corporations register. The public search lives at
  `https://www.ic.gc.ca/app/scr/cc/CorporationsCanada/fdrlCrpSrch.html` and the
  per-corp detail page is `fdrlCrpDetails.html?corpId={N}`. Both render HTML
  only — no documented JSON endpoint — so we parse defensively with regex.
- **SEDAR+** (Canadian Securities Administrators) publishes financial filings
  for listed issuers at `https://www.sedarplus.ca/`. We use the public
  party-search endpoint to discover an issuer's filing list and return PDF
  document URLs as `FinancialFiling` entries (no structured data yet — the
  per-filing XBRL would need a separate ingestion pass, out of MVP scope).

Coverage caveat: Corporations Canada covers ~1/3 of Canadian companies — the
federally incorporated ones. Provincial registries (ON, QC, BC, AB, …) are
paid per-jurisdiction services and are out of scope. OpenCorporates is used
as a resilience fallback for name search; it sometimes has provincially-
registered hits where the federal source has none.

Identifier formats:
- Corporation Number: numeric, typically 5–7 digits, often shown with a
  trailing check digit separated by a dash (e.g. ``763869-7``). We strip the
  separator and validate digits-only with length 5–8.
- Business Number (BN): 9 digits + 2-letter program + 4-digit reference (e.g.
  ``123456789RC0001``) — captured as a `VAT`-typed `RegistryIdentifier` when
  surfaced by the source, but the federal register does not key on it.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.adapters._global.opencorporates import OpenCorporatesClient
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

_CORP_NUM_RE = re.compile(r"^\d{4,8}$")
_BN_RE = re.compile(r"^\d{9}[A-Z]{2}\d{4}$")


def _normalize_corp_number(value: str) -> str:
    """Strip dashes/spaces and validate a federal Corporation Number."""
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    # Federal corp numbers are bare digits in URLs; the displayed "-N" check
    # digit is cosmetic. Validate 4–8 digits to absorb historical/short ids.
    if not _CORP_NUM_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Canadian Corporation Number invalid (expected 4–8 digits): {value}"
        )
    return cleaned


def _normalize_bn(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if not _BN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Canadian Business Number invalid (expected 9 digits + 2 letters + 4 digits): {value}"
        )
    return cleaned


class CAAdapter(CountryAdapter):
    country_code = "CA"
    country_name = "Canada"
    identifier_types = [
        IdentifierType.COMPANY_NUMBER,  # federal Corporation Number
        IdentifierType.VAT,             # Business Number (BN15)
        IdentifierType.OTHER,           # SEDAR+ profile id
    ]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 60

    CC_BASE = "https://www.ic.gc.ca"
    CC_SEARCH_PATH = "/app/scr/cc/CorporationsCanada/fdrlCrpSrch.html"
    CC_DETAILS_PATH = "/app/scr/cc/CorporationsCanada/fdrlCrpDetails.html"
    SEDAR_BASE = "https://www.sedarplus.ca"

    def __init__(self) -> None:
        self._oc = OpenCorporatesClient()

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.CC_BASE) as client:
                resp = await get_with_retry(
                    client,
                    self.CC_SEARCH_PATH,
                    params={"V_SEARCH.command": "navigate", "crpNm": "shopify"},
                )
                resp.raise_for_status()
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
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Federal corporations only. Provincial registries (ON/QC/BC/AB) "
                "are paid and out of scope. SEDAR+ covers listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        matches = await self._search_corporations_canada(name, limit)
        if matches:
            return matches
        # OpenCorporates as resilience fallback — frequently hits provincial
        # entities the federal register won't return. Free-tier: 500/mo.
        return await self._search_opencorporates(name, limit)

    async def _search_corporations_canada(
        self, name: str, limit: int
    ) -> list[CompanyMatch]:
        params = {
            "V_SEARCH.command": "navigate",
            "V_SEARCH.docsCount": str(max(limit, 10)),
            "crpNm": name,
            "crpNmStartWth": "0",
        }
        try:
            async with build_http_client(base_url=self.CC_BASE) as client:
                resp = await get_with_retry(client, self.CC_SEARCH_PATH, params=params)
                if resp.status_code >= 400:
                    return []
                html_text = resp.text
        except Exception as exc:
            logger.warning("Corporations Canada search failed: %s", exc)
            return []

        out: list[CompanyMatch] = []
        for corp_id, display_name, status in _parse_cc_results(html_text):
            if len(out) >= limit:
                break
            out.append(
                CompanyMatch(
                    id=corp_id,
                    name=display_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=corp_id,
                            label="Corporation Number",
                        )
                    ],
                    address=None,
                    status=status,
                    source_url=(
                        f"{self.CC_BASE}{self.CC_DETAILS_PATH}?corpId={corp_id}"
                    ),
                )
            )
        return out

    async def _search_opencorporates(
        self, name: str, limit: int
    ) -> list[CompanyMatch]:
        try:
            rows = await self._oc.search_companies(name, jurisdiction="ca", per_page=limit)
        except Exception as exc:
            logger.warning("OpenCorporates CA fallback failed: %s", exc)
            return []
        out: list[CompanyMatch] = []
        for r in rows[:limit]:
            cn = str(r.get("company_number") or "").strip()
            if not cn:
                continue
            out.append(
                CompanyMatch(
                    id=cn,
                    name=r.get("name", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=cn,
                            label="Corporation Number",
                        )
                    ],
                    address=r.get("registered_address_in_full"),
                    status=r.get("current_status"),
                    source_url=r.get("opencorporates_url"),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            corp_id = _normalize_corp_number(value)
            return await self._lookup_federal(corp_id)
        if id_type == IdentifierType.VAT:
            bn = _normalize_bn(value)
            # The federal register doesn't key on BN. We accept the identifier
            # for completeness but cannot resolve it without a paid CRA lookup.
            raise AdapterError(
                f"Business Number lookup ({bn}) requires CRA — not free. "
                "Search by name and pick the matching corporation."
            )
        if id_type == IdentifierType.OTHER:
            raise AdapterError(
                "SEDAR+ profile-id direct lookup not implemented; "
                "use fetch_financials with the corporation name instead."
            )
        raise InvalidIdentifierError(
            f"CA adapter supports COMPANY_NUMBER, VAT, OTHER; got {id_type}"
        )

    async def _lookup_federal(self, corp_id: str) -> CompanyDetails | None:
        params = {"corpId": corp_id, "V_SEARCH.command": "navigate"}
        try:
            async with build_http_client(base_url=self.CC_BASE) as client:
                resp = await get_with_retry(client, self.CC_DETAILS_PATH, params=params)
                if resp.status_code == 404:
                    return None
                if resp.status_code >= 400:
                    raise AdapterError(
                        f"Corporations Canada returned {resp.status_code}"
                    )
                html_text = resp.text
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Corporations Canada detail fetch failed: {exc}") from exc

        parsed = _parse_cc_details(html_text)
        if not parsed.get("name"):
            return None

        return CompanyDetails(
            id=corp_id,
            name=parsed["name"],
            country="CA",
            legal_form="Federal Corporation",
            status=parsed.get("status"),
            incorporation_date=parsed.get("incorporation_date"),
            dissolution_date=parsed.get("dissolution_date"),
            registered_address=parsed.get("registered_address"),
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=corp_id,
                    label="Corporation Number",
                )
            ],
            directors=parsed.get("directors") or [],
            raw=parsed.get("raw") or {},
            source_url=(
                f"{self.CC_BASE}{self.CC_DETAILS_PATH}?corpId={corp_id}"
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # SEDAR+ keys filings by issuer profile, not federal corp #. The
        # company-name pivot is the cheapest way without scraping the issuer
        # ticker tape. If the corp # is unknown to SEDAR (private federal
        # company), we return [] — non-listed entities don't file there.
        details = await self._lookup_federal(_normalize_corp_number(company_id))
        if not details:
            return []
        return await self._fetch_sedar_filings(details.name, company_id, years)

    async def _fetch_sedar_filings(
        self, issuer_name: str, company_id: str, years: int
    ) -> list[FinancialFiling]:
        # SEDAR+ public document search. The endpoint is public but its query
        # surface is undocumented; we hit the GET facet that the website uses
        # for the company-name pivot.
        params = {
            "keyword": issuer_name,
            "documentTypes": ",".join([
                "annual-financial-statements",
                "interim-financial-statements",
                "annual-information-form",
            ]),
        }
        try:
            async with build_http_client(base_url=self.SEDAR_BASE) as client:
                resp = await get_with_retry(
                    client,
                    "/csa-party/service/searchDocuments",
                    params=params,
                )
                if resp.status_code >= 400:
                    return []
                payload: Any = None
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype:
                    payload = resp.json()
        except Exception as exc:
            logger.warning("SEDAR+ search failed for %s: %s", issuer_name, exc)
            return []

        items: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            # SEDAR+ responses sometimes wrap rows under `data`, `documents`,
            # or `results`. Pick whichever non-empty list appears.
            for key in ("documents", "results", "data", "items"):
                v = payload.get(key)
                if isinstance(v, list) and v:
                    items = v
                    break
        elif isinstance(payload, list):
            items = payload

        filings: list[FinancialFiling] = []
        cutoff = datetime.utcnow().year - years
        for it in items:
            if not isinstance(it, dict):
                continue
            filed_raw = (
                it.get("filingDate")
                or it.get("filedDate")
                or it.get("submissionDate")
                or it.get("date")
            )
            filed = _parse_iso_date(filed_raw)
            if not filed:
                continue
            if filed.year < cutoff:
                continue
            doc_url = it.get("documentUrl") or it.get("url") or it.get("href")
            if doc_url and not doc_url.startswith("http"):
                doc_url = f"{self.SEDAR_BASE}{doc_url}"
            filings.append(
                FinancialFiling(
                    company_id=company_id,
                    year=filed.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=filed,
                    currency="CAD",
                    structured_data=None,
                    document_url=doc_url,
                    document_format="pdf",
                    source_url=f"{self.SEDAR_BASE}/landingpage/?keyword="
                    f"{issuer_name.replace(' ', '+')}",
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings


_CC_ROW_RE = re.compile(
    r'corpId=(?P<id>\d+)[^"\']*["\'][^>]*>(?P<name>[^<]+)</a>'
    r'(?:.*?<td[^>]*>(?P<status>[^<]+)</td>)?',
    re.IGNORECASE | re.DOTALL,
)


def _parse_cc_results(html_text: str) -> list[tuple[str, str, str | None]]:
    """Pull (corpId, name, status) tuples from a search result page.

    The Corporations Canada search page renders a table; each result row links
    to ``fdrlCrpDetails.html?corpId=N`` and shows the corp name + status cell.
    Tables vary slightly across views — we extract only what's stable.
    """
    out: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for m in _CC_ROW_RE.finditer(html_text):
        corp_id = m.group("id")
        if corp_id in seen:
            continue
        seen.add(corp_id)
        name = html.unescape((m.group("name") or "").strip())
        status_raw = m.group("status")
        status = html.unescape(status_raw.strip()) if status_raw else None
        if not name:
            continue
        out.append((corp_id, name, status))
    return out


_FIELD_RE = re.compile(
    r"<(?:dt|th)[^>]*>\s*(?P<label>[^<:]+?)\s*[:]?\s*</(?:dt|th)>\s*"
    r"<(?:dd|td)[^>]*>(?P<value>.*?)</(?:dd|td)>",
    re.IGNORECASE | re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_tags(s: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", s))).strip()


def _parse_cc_details(html_text: str) -> dict[str, Any]:
    """Best-effort parse of the federal corporation detail page.

    The page is HTML with French + English label variants. We pick the values
    by matching either language and normalize whitespace.
    """
    fields: dict[str, str] = {}
    for m in _FIELD_RE.finditer(html_text):
        label = _strip_tags(m.group("label")).rstrip(":").strip().lower()
        value = _strip_tags(m.group("value"))
        if label and value and label not in fields:
            fields[label] = value

    name = (
        fields.get("corporate name")
        or fields.get("corporation name")
        or fields.get("dénomination sociale")
        or _extract_h1(html_text)
    )

    status = (
        fields.get("status")
        or fields.get("statut")
        or fields.get("corporation status")
    )
    if status:
        status = status.lower()

    inc_date = _parse_loose_date(
        fields.get("date of incorporation")
        or fields.get("date of amalgamation")
        or fields.get("date de constitution")
    )
    diss_date = _parse_loose_date(
        fields.get("date of dissolution")
        or fields.get("date of revocation")
        or fields.get("date de dissolution")
    )

    address = (
        fields.get("registered office address")
        or fields.get("registered office")
        or fields.get("adresse du siège social")
        or fields.get("siège social")
    )

    directors = _parse_cc_directors(html_text)

    return {
        "name": name or "",
        "status": status,
        "incorporation_date": inc_date,
        "dissolution_date": diss_date,
        "registered_address": address,
        "directors": directors,
        "raw": fields,
    }


_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _extract_h1(html_text: str) -> str | None:
    m = _H1_RE.search(html_text)
    if not m:
        return None
    txt = _strip_tags(m.group(1))
    return txt or None


_DIRECTOR_SECTION_RE = re.compile(
    r"(?:directors?|administrateurs?)\s*</(?:h\d|caption|legend|th)>\s*"
    r"(?P<body>.*?)(?:</table>|</section>|<h\d)",
    re.IGNORECASE | re.DOTALL,
)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)


def _parse_cc_directors(html_text: str) -> list[Director]:
    section = _DIRECTOR_SECTION_RE.search(html_text)
    if not section:
        return []
    body = section.group("body")
    raw_items: list[str] = []
    for m in _LI_RE.finditer(body):
        raw_items.append(_strip_tags(m.group(1)))
    if not raw_items:
        for m in _TR_RE.finditer(body):
            raw_items.append(_strip_tags(m.group(1)))
    directors: list[Director] = []
    for item in raw_items:
        if not item:
            continue
        # First comma-separated token is conventionally the name.
        name = item.split(",", 1)[0].strip()
        if not name or name.lower() in {"name", "nom"}:
            continue
        directors.append(Director(name=name))
        if len(directors) >= 50:
            break
    return directors


_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LONG_DATE_RE = re.compile(
    r"(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})"
)


def _parse_loose_date(s: str | None) -> date | None:
    if not s:
        return None
    m = _ISO_DATE_RE.search(s)
    if m:
        try:
            return date.fromisoformat(m.group(0))
        except ValueError:
            return None
    m = _LONG_DATE_RE.search(s)
    if m:
        try:
            return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None
    return None


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None
