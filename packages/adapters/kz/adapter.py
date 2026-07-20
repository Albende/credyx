"""Kazakhstan adapter — adata.kz counterparty API + DFO financial-statements depository.

Source coverage (all free, no API key):

* ``https://pk-api.adata.kz/api/v1/data/search`` — public backend of the
  adata.kz counterparty checker (pk.adata.kz). Full-text search over the
  Kazakhstan legal-entity register (sourced by adata from stat.gov.kz,
  kgd.gov.kz and egov.kz). Returns BIN, name, address, director, status and
  registration date. Searching the BIN itself returns the single matching
  entity, so it doubles as a lookup endpoint. No auth, no session cookie.
* ``https://pk-api.adata.kz/api/v1/data/company/authorized-capital/short`` —
  charter capital and government-participation share (source: egov.kz). Works
  key-free and without opening a metered card.
* ``https://opi.dfo.kz`` — Депозитарий финансовой отчётности, the Ministry of
  Finance financial-statements depository. Every public-interest organisation
  (listed issuers, banks, subsoil users, state-participation entities, etc.)
  files annual IFRS / form-665 accounts here. The site exposes JSON endpoints
  (``/ru/report-json/{object}/...``) that list filed reports per company and
  the reporting year of each. Companies that are not public-interest filers
  return no reports — we surface that as an empty list, never a fabricated one.

Identifier:
- BIN (Бизнес-сәйкестендіру нөмірі / Бизнес-идентификационный номер) — 12
  digits, issued to every legal entity. Both VAT and COMPANY_NUMBER identifier
  types map to the BIN — it is the canonical taxpayer/registration id, so
  callers may legitimately hand us either label.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

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

_BIN_RE = re.compile(r"^\d{12}$")

# KazMunayGas — well-known active state-owned issuer used as liveness probe.
_HEALTH_PROBE_BIN = "020240000555"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# DFO groups filed reports under plugins (report taxonomies). Annual financial
# statements live under the IFRS plugin (financial organisations) and the
# form-665 plugin (non-financial organisations); everything else on the portal
# is quarterly / affiliation / corporate-event filings we don't treat as a
# company's annual accounts.
_ANNUAL_PLUGIN_MARKERS = ("МСФО", "665")

_DFO_VIEW_RE = re.compile(r"/ru/opi/list/(\d+)/view")


def _normalize_bin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("KZ"):
        cleaned = cleaned[2:]
    if not _BIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kazakhstan BIN must be exactly 12 digits, got: {value}"
        )
    return cleaned


def _parse_reg_date(value: str | None) -> date | None:
    """adata emits registration dates as ``DD-MM-YYYY (age)``."""
    if not value:
        return None
    m = re.match(r"\s*(\d{1,2})[-./](\d{1,2})[-./](\d{4})", str(value))
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


class KZAdapter(CountryAdapter):
    country_code = "KZ"
    country_name = "Kazakhstan"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    ADATA_API_URL = "https://pk-api.adata.kz"
    ADATA_WEB_URL = "https://pk.adata.kz"
    DFO_BASE_URL = "https://opi.dfo.kz"

    def _adata_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.ADATA_API_URL,
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru,kk;q=0.8,en;q=0.6",
                "User-Agent": _BROWSER_UA,
                "Origin": self.ADATA_WEB_URL,
                "Referer": f"{self.ADATA_WEB_URL}/",
            },
            timeout=25.0,
        )

    def _dfo_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.DFO_BASE_URL,
            headers={
                "Accept": "application/json, text/html;q=0.8",
                "Accept-Language": "ru,kk;q=0.8,en;q=0.6",
                "User-Agent": _BROWSER_UA,
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._adata_client() as client:
                resp = await get_with_retry(
                    client,
                    "/api/v1/data/search",
                    params={"most_viewed_companies": 0, "keyword": _HEALTH_PROBE_BIN},
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"adata.kz unreachable: {exc}"[:200],
            )

        if resp.status_code >= 500:
            status = AdapterStatus.DEGRADED
            notes = f"adata.kz probe returned HTTP {resp.status_code}."
        else:
            status = AdapterStatus.OK
            notes = (
                "Search + BIN lookup via adata.kz (free public counterparty "
                "API). Financials via DFO depository for public-interest filers."
            )

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def _search_raw(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        async with self._adata_client() as client:
            resp = await get_with_retry(
                client,
                "/api/v1/data/search",
                params={"most_viewed_companies": 0, "keyword": keyword},
            )
        if resp.status_code >= 400:
            logger.warning("adata.kz search HTTP %s for %r", resp.status_code, keyword)
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        if not payload.get("status"):
            return []
        result = (payload.get("data") or {}).get("result") or []
        return [r for r in result if isinstance(r, dict)][:limit]

    def _match_from_record(self, record: dict[str, Any]) -> CompanyMatch:
        bin_value = str(record.get("biin") or record.get("id") or "").strip()
        status = record.get("status")
        if record.get("is_inactive"):
            status = status or "inactive"
        return CompanyMatch(
            id=bin_value,
            name=str(record.get("name") or "").strip(),
            country=self.country_code,
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=bin_value, label="BIN"),
            ],
            address=record.get("address") or None,
            status=status,
            source_url=f"{self.ADATA_WEB_URL}/company/{bin_value}",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        keyword = name.strip()
        if not keyword:
            return []
        records = await self._search_raw(keyword, limit)
        return [self._match_from_record(r) for r in records if r.get("biin")]

    async def _fetch_authorized_capital(self, bin_value: str) -> dict[str, Any] | None:
        async with self._adata_client() as client:
            try:
                resp = await get_with_retry(
                    client,
                    "/api/v1/data/company/authorized-capital/short",
                    params={"id": bin_value, "initial": 1},
                )
            except httpx.HTTPError as exc:
                logger.warning("adata.kz capital lookup failed for %s: %s", bin_value, exc)
                return None
        if resp.status_code >= 400:
            return None
        try:
            payload = resp.json()
        except ValueError:
            return None
        if not payload.get("status"):
            return None
        return (payload.get("data") or {}).get("result") or None

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Kazakhstan adapter accepts VAT or COMPANY_NUMBER (BIN), got {id_type}"
            )
        bin_value = _normalize_bin(value)

        records = await self._search_raw(bin_value, limit=10)
        record = next((r for r in records if str(r.get("biin")) == bin_value), None)
        if record is None:
            return None

        capital = await self._fetch_authorized_capital(bin_value)
        capital_amount = _coerce_float(capital.get("capital")) if capital else None

        directors: list[Director] = []
        director_name = (record.get("director_name") or "").strip()
        if director_name:
            directors.append(Director(name=director_name, role="Director"))

        status = record.get("status")
        if record.get("is_inactive"):
            status = status or "inactive"

        return CompanyDetails(
            id=bin_value,
            name=str(record.get("name") or "").strip(),
            country=self.country_code,
            status=status,
            incorporation_date=_parse_reg_date(record.get("registration_date")),
            registered_address=record.get("address") or None,
            capital_amount=capital_amount,
            capital_currency="KZT" if capital_amount is not None else None,
            directors=directors,
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=bin_value, label="BIN"),
            ],
            raw={"source": "adata.kz", "search": record, "capital": capital},
            source_url=f"{self.ADATA_WEB_URL}/company/{bin_value}",
        )

    async def _resolve_dfo_object_id(
        self, client: httpx.AsyncClient, bin_value: str
    ) -> str | None:
        resp = await get_with_retry(client, "/ru/opi/list", params={"flBin": bin_value})
        if resp.status_code >= 400:
            return None
        body = resp.text
        if f"БИН: {bin_value}" not in body and bin_value not in body:
            return None
        m = _DFO_VIEW_RE.search(body)
        return m.group(1) if m else None

    async def _dfo_json(
        self, client: httpx.AsyncClient, path: str, **params: Any
    ) -> Any:
        resp = await get_with_retry(client, path, params=params or None)
        if resp.status_code >= 400:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    async def _report_period(
        self, client: httpx.AsyncClient, object_id: str, plugin_id: str, report_id: int
    ) -> tuple[int, str] | None:
        """Read a filed report's info block → (fiscal_year, period_label)."""
        resp = await get_with_retry(
            client,
            f"/ru/render-blocks/{object_id}/get-node-data",
            params={"pluginId": plugin_id, "reportId": report_id, "nodeId": 1},
        )
        if resp.status_code >= 400:
            return None
        text = html.unescape(re.sub(r"<[^>]+>", " ", resp.text))
        year_m = re.search(r"Год:\s*(\d{4})", text)
        if not year_m:
            return None
        period_m = re.search(r"Период:\s*([^\s<]+)", text)
        return int(year_m.group(1)), (period_m.group(1) if period_m else "")

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        bin_value = _normalize_bin(company_id)

        async with self._dfo_client() as client:
            object_id = await self._resolve_dfo_object_id(client, bin_value)
            if not object_id:
                return []

            plugins = await self._dfo_json(
                client, f"/ru/report-json/{object_id}/get-plugins"
            )
            if not isinstance(plugins, list):
                return []

            annual = [
                p
                for p in plugins
                if isinstance(p, dict)
                and (p.get("ReportsCount") or 0) > 0
                and any(m in (p.get("PluginName") or "") for m in _ANNUAL_PLUGIN_MARKERS)
            ]
            annual.sort(
                key=lambda p: 0 if "МСФО" in (p.get("PluginName") or "") else 1
            )

            filings: list[FinancialFiling] = []
            seen_years: set[int] = set()

            for plugin in annual:
                if len(seen_years) >= years:
                    break
                plugin_id = plugin.get("PluginId")
                plugin_name = plugin.get("PluginName") or ""
                reports = await self._dfo_json(
                    client,
                    f"/ru/report-json/{object_id}/get-reports",
                    pluginId=plugin_id,
                )
                if not isinstance(reports, list):
                    continue
                reports = [r for r in reports if isinstance(r, dict) and r.get("ReportId")]
                reports.sort(key=lambda r: r.get("LoadDate") or "", reverse=True)

                for report in reports:
                    if len(seen_years) >= years:
                        break
                    report_id = int(report["ReportId"])
                    period = await self._report_period(
                        client, object_id, plugin_id, report_id
                    )
                    if period is None:
                        continue
                    year, period_label = period
                    if "Год" not in period_label:
                        continue
                    if year in seen_years:
                        continue
                    seen_years.add(year)
                    source_url = (
                        f"{self.DFO_BASE_URL}/ru/opi/list/{object_id}/view"
                        f"?SelectedPluginId={plugin_id}&SelectedReportId={report_id}"
                    )
                    filings.append(
                        FinancialFiling(
                            company_id=bin_value,
                            year=year,
                            type=FilingType.ANNUAL_REPORT,
                            period_end=date(year, 12, 31),
                            currency="KZT",
                            structured_data={
                                "report_id": report_id,
                                "plugin": plugin_name,
                                "load_date": report.get("LoadDate"),
                                "period": period_label,
                            },
                            document_url=None,
                            document_format=None,
                            source_url=source_url,
                        )
                    )

        filings.sort(key=lambda f: f.year, reverse=True)
        return filings
