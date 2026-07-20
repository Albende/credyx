"""Georgia adapter — NAPR business register + SARAS reporting portal.

Two free, key-free public sources are stitched together:

* ``https://enreg.reestri.gov.ge/main.php`` — the NAPR (National Agency of
  Public Registry) business register. Its search form POSTs
  ``c=search&m=find_legal_persons`` and server-renders a result table with
  the 9-digit Identification Number, registered name, legal form, and
  status. This is the authoritative existence + status check and covers
  every registered legal person. The per-company detail page
  (``show_legal_person``) is CAPTCHA-gated and is deliberately not used.

* ``https://reportal.ge`` — the public Reporting Portal operated by the
  Service for Accounting, Reporting and Auditing Supervision (SARAS),
  where category I–IV entities file annual financial statements. Three
  key-free endpoints are used:
    - ``/en/Reports/GetProfileData?q=<id>`` → JSON profile (registration
      date, address, phone, web, activity, directors) used to enrich the
      registry record without hitting the NAPR captcha.
    - ``/en/Reports/OrgReports?q=<id>`` → the company-specific list of
      reporting years that actually have filings.
    - ``/en/Reports/OrgReportsByYear?q=<id>&year=<yyyy>`` → per-year filing
      page whose audit tab exposes the auditor + reporting year.

  The financial-statement PDFs themselves are released only after an SMS
  one-time-code flow, so ``fetch_financials`` returns real per-company
  filing metadata (year, type, currency, source_url, auditor) but never a
  ``document_url`` — the document does not download key-free.

Identifier:
- VAT / COMPANY_NUMBER → "Identification Number" (საიდენტიფიკაციო
  ნომერი), always 9 digits. The same number serves as the corporate tax
  ID, the VAT registration ID, and the commercial registry primary key.
  NAPR does not issue a separate company number.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
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
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^\d{9}$")

# Bank of Georgia — a well-known active legal person used as a liveness probe.
_HEALTH_PROBE_ID = "204378869"

_STATUS_ACTIVE_TOKENS = (
    "მოქმედი",
    "აქტიური",
    "active",
    "registered",
)
_STATUS_INACTIVE_TOKENS = (
    "გაუქმებული",
    "ლიკვიდირებული",
    "შეჩერებული",
    "გადახდისუუნარო",
    "liquidated",
    "cancelled",
    "suspended",
    "inactive",
    "dissolved",
)

_TAG_RE = re.compile(r"<[^>]+>")
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_RECORD_RE = re.compile(r"show_legal_person\((\d+)\)")
_YEAR_RE = re.compile(r'data-year="(\d{4})"')
_SARAS_REG_RE = re.compile(r"SARAS-A-\d+")


def _normalize_id(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("GE"):
        cleaned = cleaned[2:]
    if not _ID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Georgia Identification Number must be exactly 9 digits, got: {value}"
        )
    return cleaned


def _parse_ge_date(value: str | None) -> date | None:
    """Reportal renders ISO dates; NAPR uses DD.MM.YYYY — tolerate both."""
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(token in low for token in _STATUS_INACTIVE_TOKENS):
        return "inactive"
    if any(token in raw for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _cell_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", fragment))).strip()


def _parse_search_rows(html: str) -> list[dict[str, Any]]:
    """Pull legal-person rows out of the NAPR find_legal_persons table.

    Columns render as ``[info icon, id code, personal no, name, legal
    form, status]``. Rows without a 9-digit id code (individual persons
    keyed only on a personal number) are skipped — the adapter targets
    legal persons.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_match in _ROW_RE.finditer(html or ""):
        row_html = row_match.group(1)
        record = _RECORD_RE.search(row_html)
        if not record:
            continue
        cells = [_cell_text(c) for c in _TD_RE.findall(row_html)]
        id_index = next(
            (i for i, c in enumerate(cells) if _ID_RE.match(c.replace(" ", ""))),
            None,
        )
        if id_index is None:
            continue
        id_code = cells[id_index].replace(" ", "")
        if id_code in seen:
            continue
        seen.add(id_code)

        def _at(offset: int) -> str | None:
            idx = id_index + offset
            return cells[idx] if 0 <= idx < len(cells) else None

        out.append(
            {
                "id": id_code,
                "record_id": record.group(1),
                "name": _at(2) or "",
                "legal_form": _at(3),
                "status_raw": _at(4),
            }
        )
    return out


def _reportal_directors(payload: dict[str, Any]) -> list[Director]:
    raw = payload.get("directors")
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[Director] = []
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = f"{entry.get('FirstName', '') or ''} {entry.get('LastName', '') or ''}".strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(Director(name=name, role=entry.get("PersonType") or None))
    return out


class GEAdapter(CountryAdapter):
    country_code = "GE"
    country_name = "Georgia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    NAPR_BASE = "https://enreg.reestri.gov.ge"
    NAPR_PATH = "/main.php"
    REPORTAL_BASE = "https://reportal.ge"

    def _napr_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.NAPR_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ka,en;q=0.7,ru;q=0.5",
            },
            timeout=25.0,
        )

    def _reportal_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.REPORTAL_BASE,
            headers={"Accept": "application/json, text/html"},
            timeout=25.0,
        )

    async def _napr_search(
        self, *, idnumber: str = "", name: str = ""
    ) -> list[dict[str, Any]]:
        data = {
            "c": "search",
            "m": "find_legal_persons",
            "s_legal_person_idnumber": idnumber,
            "s_legal_person_name": name,
            "s_legal_person_form": "0",
            "s_legal_person_email": "",
        }
        async with self._napr_client() as client:
            resp = await client.post(self.NAPR_PATH, data=data)
            resp.raise_for_status()
            return _parse_search_rows(resp.text)

    async def _reportal_profile(self, legal_code: str) -> dict[str, Any]:
        try:
            async with self._reportal_client() as client:
                resp = await get_with_retry(
                    client,
                    "/en/Reports/GetProfileData",
                    params={"q": legal_code},
                )
            if resp.status_code != 200:
                return {}
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("GE reportal profile fetch failed for %s: %s", legal_code, exc)
            return {}
        return payload if isinstance(payload, dict) and payload.get("id_code") else {}

    async def health_check(self) -> AdapterHealth:
        try:
            rows = await self._napr_search(idnumber=_HEALTH_PROBE_ID)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        if not any(r["id"] == _HEALTH_PROBE_ID for r in rows):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "enreg.reestri.gov.ge responded but the probe ID returned no "
                    "row; result markup may have changed."
                ),
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
                "NAPR register (search + lookup) enriched by the SARAS reportal.ge "
                "portal; financials return filing metadata, statement PDFs are "
                "SMS-gated."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        query = (name or "").strip()
        if not query:
            return []

        rows = await self._napr_search(name=query)
        out: list[CompanyMatch] = []
        for row in rows[:limit]:
            legal_code = row["id"]
            out.append(
                CompanyMatch(
                    id=legal_code,
                    name=row.get("name", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT,
                            value=legal_code,
                            label="Identification Number",
                        ),
                    ],
                    status=_classify_status(row.get("status_raw")),
                    source_url=(
                        f"{self.NAPR_BASE}{self.NAPR_PATH}?c=app&"
                        f"m=show_legal_person&legal_code={legal_code}"
                    ),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                "Georgia adapter accepts only VAT or COMPANY_NUMBER "
                f"(9-digit Identification Number), got {id_type}"
            )
        legal_code = _normalize_id(value)

        rows = await self._napr_search(idnumber=legal_code)
        row = next((r for r in rows if r["id"] == legal_code), None)
        if row is None:
            return None

        profile = await self._reportal_profile(legal_code)

        directors = _reportal_directors(profile)
        website = (profile.get("web") or "").strip() or None
        phone = (profile.get("phone") or "").strip() or None
        address = (profile.get("address") or "").strip() or None
        incorporation = _parse_ge_date(profile.get("registration_date"))
        legal_form = row.get("legal_form") or profile.get("form") or None

        return CompanyDetails(
            id=legal_code,
            name=row.get("name") or profile.get("name") or "",
            country=self.country_code,
            legal_form=legal_form,
            status=_classify_status(row.get("status_raw")),
            incorporation_date=incorporation,
            registered_address=address,
            website=website,
            phone=phone,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=legal_code,
                    label="Identification Number",
                ),
            ],
            directors=directors,
            raw={
                "napr": row,
                "reportal_profile": profile or None,
            },
            source_url=(
                f"{self.NAPR_BASE}{self.NAPR_PATH}?c=app&"
                f"m=show_legal_person&legal_code={legal_code}"
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        legal_code = _normalize_id(company_id)

        async with self._reportal_client() as client:
            resp = await get_with_retry(
                client, "/en/Reports/OrgReports", params={"q": legal_code}
            )
            if resp.status_code != 200:
                return []
            reporting_years = sorted(
                {int(y) for y in _YEAR_RE.findall(resp.text)}, reverse=True
            )
            if not reporting_years:
                return []

            report_url = f"{self.REPORTAL_BASE}/en/Reports/Report?q={legal_code}"
            filings: list[FinancialFiling] = []
            for year in reporting_years[: max(years, 1)]:
                audit = await self._year_audit(client, legal_code, year)
                filings.append(
                    FinancialFiling(
                        company_id=legal_code,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        currency="GEL",
                        structured_data=audit or None,
                        document_url=None,
                        source_url=report_url,
                    )
                )
        return filings

    async def _year_audit(
        self, client: httpx.AsyncClient, legal_code: str, year: int
    ) -> dict[str, Any]:
        """Parse the public audit tab of a per-year filing page.

        Category III/IV filers may not be audited, in which case the tab is
        empty and we return ``{}`` — the filing metadata is still valid.
        """
        try:
            resp = await get_with_retry(
                client,
                "/en/Reports/OrgReportsByYear",
                params={"q": legal_code, "year": year},
            )
        except httpx.HTTPError:
            return {}
        if resp.status_code != 200:
            return {}

        html = resp.text
        audit_start = html.find('id="reports-audit"')
        if audit_start == -1:
            return {}
        audit_end = html.find('id="reports-group"', audit_start)
        block = html[audit_start : audit_end if audit_end != -1 else len(html)]

        reg = _SARAS_REG_RE.search(block)
        firm_id = next(
            (m for m in re.findall(r"\b\d{9}\b", block) if m != legal_code), None
        )
        auditor = re.search(
            r"AuditorDetail/\d+[^>]*>\s*([^<]+?)\s*<", block
        )
        result: dict[str, Any] = {}
        if reg:
            result["auditor_registration"] = reg.group(0)
        if firm_id:
            result["auditor_firm_id"] = firm_id
        if auditor:
            result["auditor_partner"] = auditor.group(1).strip()
        return result
