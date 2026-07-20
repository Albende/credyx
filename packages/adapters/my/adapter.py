"""Malaysia adapter — GLEIF registry lookup + Bursa Malaysia filings.

The Companies Commission of Malaysia (SSM / Suruhanjaya Syarikat Malaysia)
runs the only authoritative corporate register, but every programmatic and
human-readable full-record lookup on https://www.ssm-einfo.my/ is paid
(per-document charges) and gated behind login + reCAPTCHA — excluded by the
project's "no paid APIs" rule. This adapter therefore stitches together two
free, key-less public sources:

* **GLEIF** (https://api.gleif.org) — the Global LEI index. Every Malaysian
  legal entity with an LEI carries its SSM registration number in the
  ``registeredAs`` field (validated by the local LOU against SSM), so GLEIF
  gives real name-search and identifier-lookup for the large / trading /
  listed universe that credit decisions care about. Companies without an LEI
  simply return no match — never a fabricated one.
* **Bursa Malaysia** (https://www.bursamalaysia.com) — the local stock
  exchange publishes every listed issuer's annual reports for free. The
  public site sits behind a Cloudflare challenge, so all Bursa calls route
  through ``fetch_with_bot_bypass`` (FlareSolverr). ``fetch_financials``
  resolves an SSM registration number to the issuer's stock code via GLEIF
  (name) + Bursa's listed-company directory, then returns the filed annual
  reports with their real disclosure-page URLs and PDF attachments.

Identifier formats accepted (all map to ``IdentifierType.COMPANY_NUMBER``):

* **New format** — 12 digits, e.g. ``196501000672`` (mandatory since 2019).
* **Old format** — up to 7 digits + a check letter, e.g. ``6463-H`` /
  ``20076-K``. Normalised to ``DIGITS-LETTER`` uppercase.

A caller may also pass ``BURSA:<code>`` (e.g. ``BURSA:1295``) to
``fetch_financials`` to skip the registration-number → stock-code resolution.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
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

logger = logging.getLogger(__name__)

_NEW_REG_RE = re.compile(r"^\d{12}$")
_OLD_REG_RE = re.compile(r"^\d{1,7}-[A-Z]$")
_PACKED_BURSA_RE = re.compile(r"^BURSA[:/](?P<code>\d{3,6})$", re.IGNORECASE)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalize_company_number(value: str) -> str:
    """Normalise to either ``NNNNNNNNNNNN`` (12 digits) or ``NNNNNNN-L``.

    Accepts the historical hyphenless old form (``20076K``), mixed-case check
    letters, and a leading ``MY`` / ``CR:`` prefix. Never invents a check
    letter when one is missing.
    """
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned.startswith("MY"):
        cleaned = cleaned[2:]
    if cleaned.startswith("CR:"):
        cleaned = cleaned[3:]

    if _NEW_REG_RE.match(cleaned):
        return cleaned

    if "-" not in cleaned:
        m = re.match(r"^(\d{1,7})([A-Z])$", cleaned)
        if m:
            cleaned = f"{m.group(1)}-{m.group(2)}"

    if _OLD_REG_RE.match(cleaned):
        digits, _, letter = cleaned.partition("-")
        return f"{digits}-{letter}"

    raise InvalidIdentifierError(
        "Malaysia company number must be either the 12-digit new-format "
        f"registration number or the legacy DIGITS-LETTER form, got: {value}"
    )


def _norm_name(value: str) -> str:
    upper = re.sub(r"\bBHD\b", "BERHAD", value.upper())
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", upper)).strip()


def _ssm_ids_from_registered_as(registered_as: str | None) -> tuple[str | None, str | None]:
    """Split GLEIF's ``registeredAs`` (e.g. ``196501000672 (6463-H)``) into
    the new 12-digit and legacy DIGITS-LETTER forms."""
    if not registered_as:
        return None, None
    up = registered_as.upper()
    new = m.group(1) if (m := re.search(r"\b(\d{12})\b", up)) else None
    old = m.group(1) if (m := re.search(r"\b(\d{1,7}-[A-Z])\b", up)) else None
    return new, old


def _parse_human_date(value: Any) -> date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", s)
    if m and (mon := _MONTHS.get(m.group(2)[:3].lower())):
        try:
            return date(int(m.group(3)), mon, int(m.group(1)))
        except ValueError:
            return None
    return None


def _json_from_body(body: str) -> Any:
    """Parse a JSON payload that may be wrapped by FlareSolverr in an
    ``<html><body><pre>…</pre>`` shell (or served raw by httpx)."""
    text = body.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"<pre[^>]*>(.*?)</pre>", body, re.DOTALL | re.IGNORECASE)
    if m:
        return json.loads(html.unescape(m.group(1)))
    start, end = body.find("{"), body.rfind("}")
    if start != -1 and end > start:
        return json.loads(html.unescape(body[start : end + 1]))
    raise ValueError("no JSON payload found in response body")


class MYAdapter(CountryAdapter):
    country_code = "MY"
    country_name = "Malaysia"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    BURSA_BASE = "https://www.bursamalaysia.com"
    DISCLOSURE_BASE = "https://disclosure.bursamalaysia.com"

    # --- GLEIF registry (search + lookup) -----------------------------------

    async def _gleif_records(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        cleaned = name.strip()
        if not cleaned:
            return []
        records = await self._gleif_records(
            {
                "filter[entity.legalName]": cleaned,
                "filter[entity.legalAddress.country]": "MY",
                "page[size]": max(1, min(int(limit), 200)),
                "page[number]": 1,
            }
        )
        matches: list[CompanyMatch] = []
        for record in records:
            match = self._record_to_match(record)
            if match:
                matches.append(match)
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Malaysia only supports COMPANY_NUMBER, got {id_type}"
            )
        normalized = _normalize_company_number(value)
        records = await self._gleif_records(
            {"filter[fulltext]": normalized, "page[size]": 10, "page[number]": 1}
        )
        digits = normalized.replace("-", "")
        for record in records:
            registered_as = (
                (record.get("attributes") or {}).get("entity") or {}
            ).get("registeredAs") or ""
            if normalized in registered_as.upper() or digits in registered_as.replace("-", ""):
                return self._record_to_details(record)
        return None

    def _identifiers(self, entity: dict[str, Any], lei: str) -> list[RegistryIdentifier]:
        identifiers = [RegistryIdentifier(type=IdentifierType.LEI, value=lei)]
        new_id, old_id = _ssm_ids_from_registered_as(entity.get("registeredAs"))
        if new_id:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=new_id, label="SSM new")
            )
        if old_id:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=old_id, label="SSM old")
            )
        return identifiers

    def _record_to_match(self, record: dict[str, Any]) -> CompanyMatch | None:
        lei = record.get("id")
        entity = (record.get("attributes") or {}).get("entity") or {}
        name = (entity.get("legalName") or {}).get("name")
        if not lei or not name:
            return None
        new_id, old_id = _ssm_ids_from_registered_as(entity.get("registeredAs"))
        status_raw = (entity.get("status") or "").upper()
        return CompanyMatch(
            id=new_id or old_id or str(lei),
            name=str(name),
            country="MY",
            identifiers=self._identifiers(entity, str(lei)),
            address=_format_address(entity.get("legalAddress")),
            status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
            source_url=f"https://search.gleif.org/#/record/{lei}",
        )

    def _record_to_details(self, record: dict[str, Any]) -> CompanyDetails | None:
        lei = record.get("id")
        entity = (record.get("attributes") or {}).get("entity") or {}
        name = (entity.get("legalName") or {}).get("name")
        if not lei or not name:
            return None
        new_id, old_id = _ssm_ids_from_registered_as(entity.get("registeredAs"))
        status_raw = (entity.get("status") or "").upper()
        legal_form = (entity.get("legalForm") or {}).get("id")
        return CompanyDetails(
            id=new_id or old_id or str(lei),
            name=str(name),
            country="MY",
            legal_form=str(legal_form) if legal_form else None,
            status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
            incorporation_date=_parse_human_date(entity.get("creationDate")),
            registered_address=_format_address(entity.get("legalAddress")),
            identifiers=self._identifiers(entity, str(lei)),
            raw=record,
            source_url=f"https://search.gleif.org/#/record/{lei}",
        )

    # --- Bursa Malaysia (financials) ----------------------------------------

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raw = company_id.strip().replace(" ", "")
        packed = _PACKED_BURSA_RE.match(raw)
        if packed:
            stock_code = packed.group("code")
            source_id = f"BURSA:{stock_code}"
        else:
            normalized = _normalize_company_number(company_id)
            details = await self.lookup_by_identifier(
                IdentifierType.COMPANY_NUMBER, normalized
            )
            if details is None:
                return []
            stock_code = await self._resolve_stock_code(details.name)
            if stock_code is None:
                return []
            source_id = normalized

        return await self._fetch_bursa_annual_reports(stock_code, source_id, years)

    async def _bursa_json(self, path: str) -> Any:
        body, status, _ = await fetch_with_bot_bypass(
            f"{self.BURSA_BASE}{path}", timeout=45.0
        )
        if status in (401, 403, 404):
            return {}
        return _json_from_body(body)

    async def _resolve_stock_code(self, name: str) -> str | None:
        target = _norm_name(name)
        payload = await self._bursa_json(
            "/api/v1/announcements/search"
            f"?ann_type=company&keyword={quote(name)}&per_page=40&page=1"
        )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return None
        for row in rows:
            company_cell = row[2] if isinstance(row, list) and len(row) > 2 else None
            if not isinstance(company_cell, str):
                continue
            m = re.search(r"stock_code=(\d+)[^>]*>([^<]+)<", company_cell)
            if m and _norm_name(m.group(2)) == target:
                return m.group(1)
        return None

    async def _fetch_bursa_annual_reports(
        self, stock_code: str, source_id: str, years: int
    ) -> list[FinancialFiling]:
        payload = await self._bursa_json(
            "/api/v1/announcements/search"
            f"?ann_type=company&company={stock_code}"
            "&keyword=annual%20report&per_page=50&page=1"
        )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []

        parsed: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 4:
                continue
            title = re.sub(r"<[^>]+>", "", str(row[3])).strip()
            if "annual report" not in title.lower():
                continue
            ann_id = m.group(1) if (m := re.search(r"ann_id=(\d+)", str(row[3]))) else None
            ann_date = _parse_human_date(re.sub(r"<[^>]+>", " ", str(row[1])))
            year = _title_year(title) or (ann_date.year if ann_date else None)
            if ann_id is None or year is None:
                continue
            parsed.append({"ann_id": ann_id, "year": year, "title": title, "ann_date": ann_date})

        parsed.sort(key=lambda r: r["year"], reverse=True)
        seen: set[int] = set()
        filings: list[FinancialFiling] = []
        for row in parsed:
            if row["year"] in seen:
                continue
            seen.add(row["year"])
            if len(filings) >= max(1, years):
                break
            period_end, document_url = await self._enrich_from_disclosure(row["ann_id"])
            filings.append(
                FinancialFiling(
                    company_id=source_id,
                    year=row["year"],
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="MYR",
                    document_url=document_url,
                    document_format="pdf" if document_url else "html",
                    source_url=(
                        f"{self.BURSA_BASE}/market_information/announcements/"
                        f"company_announcement/announcement_details?ann_id={row['ann_id']}"
                    ),
                )
            )
        return filings

    async def _enrich_from_disclosure(
        self, ann_id: str
    ) -> tuple[date | None, str | None]:
        """Read the official disclosure page for one announcement to recover
        the real financial-year-end and the first PDF attachment URL.

        Retries once because the Cloudflare-bypass path is occasionally
        transiently served a partial challenge page.
        """
        url = f"{self.DISCLOSURE_BASE}/FileAccess/viewHtml?e={ann_id}"
        for attempt in range(2):
            try:
                body, status, _ = await fetch_with_bot_bypass(url, timeout=45.0)
            except Exception as exc:
                logger.debug("Disclosure enrich failed for ann_id=%s: %s", ann_id, exc)
                continue
            if status >= 400:
                continue

            period_end = None
            if m := re.search(
                r"Financial Year Ended</td>\s*<td[^>]*>([^<]+)</td>", body, re.IGNORECASE
            ):
                period_end = _parse_human_date(m.group(1))

            document_url = None
            if m := re.search(
                r'href="(/FileAccess/apbursaweb/download\?id=\d+[^"]*)"', body, re.IGNORECASE
            ):
                document_url = self.DISCLOSURE_BASE + html.unescape(m.group(1))

            if period_end or document_url:
                return period_end, document_url
        return None, None

    async def health_check(self) -> AdapterHealth:
        try:
            records = await self._gleif_records(
                {
                    "filter[entity.legalAddress.country]": "MY",
                    "page[size]": 1,
                    "page[number]": 1,
                }
            )
            gleif_ok = len(records) > 0
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"GLEIF unreachable: {str(exc)[:150]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if gleif_ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=False,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "Registry search/lookup via GLEIF (LEI-holding entities only); "
                "financials via Bursa Malaysia annual reports for listed issuers. "
                "SSM e-Info full extracts remain paid and are excluded."
            ),
        )


def _format_address(address: Any) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    for key in ("city", "region", "postalCode", "country"):
        if val := address.get(key):
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


def _title_year(title: str) -> int | None:
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", title)]
    return max(years) if years else None
