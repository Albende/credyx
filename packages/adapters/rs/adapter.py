"""Serbia adapter — APR (Agencija za privredne registre) open-data API.

Sources (all free, no auth, no key):

* Company register open data —
  ``https://openapi.apr.gov.rs/api/opendata/companies``. A single JSON
  document keyed by Matični broj (MB) holding one record per registered
  company (privredno društvo): business name, seat municipality, status,
  founding date, legal form, and primary activity code.
* Financial-statements register (RGFI) open data —
  ``https://openapi.apr.gov.rs/api/opendata/companies/financial-statements``.
  A JSON document keyed by MB carrying the latest filed annual figures:
  total assets, capital, revenue, net profit / loss, and headcount. Amounts
  are reported in thousands of RSD; we scale to absolute RSD.

Both endpoints are bulk snapshots (``DatumPreseka``) refreshed monthly with
no server-side filtering — there is no per-company query. We download each
document once and cache it in-process; searches and lookups run over the
cached snapshot.

The interactive portal ``pretraga2.apr.gov.rs`` (unified entity search and
per-filing PDF download) geoblocks non-Serbian traffic and is unreachable
from our infrastructure, so PDF documents are not surfaced — we never pass
off a landing page as a company's filing.

Identifiers: Matični broj (MB) — 8-digit company registration number,
primary. PIB (tax id) is not present in the open datasets, so it is not
resolvable through this free source.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

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

_MB_LEN = 8
_STATUS_ACTIVE_TOKENS = ("активан", "aktivan", "активно", "aktivno", "active")
_STATUS_CEASED_TOKENS = (
    "брисан",
    "brisan",
    "ликвидац",
    "likvidac",
    "стеч",
    "stec",
    "steč",
    "престал",
    "prestal",
)
_DIACRITIC_FOLD = str.maketrans(
    {
        "č": "c", "ć": "c", "đ": "dj", "š": "s", "ž": "z",
        "Č": "c", "Ć": "c", "Đ": "dj", "Š": "s", "Ž": "z",
    }
)

_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = asyncio.Lock()


def _normalize_mb(value: str) -> str:
    cleaned = "".join(ch for ch in value.strip() if ch.isdigit())
    if len(cleaned) != _MB_LEN:
        raise InvalidIdentifierError(
            f"Serbian Matični broj must be exactly {_MB_LEN} digits, got: {value}"
        )
    return cleaned


def _fold(text: str) -> str:
    return text.translate(_DIACRITIC_FOLD).casefold()


def _parse_rs_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.casefold()
    if any(token in low for token in _STATUS_CEASED_TOKENS):
        return "ceased"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _to_rsd(value_thousands: Any) -> float | None:
    n = _as_int(value_thousands)
    return None if n is None else float(n) * 1000.0


class RSAdapter(CountryAdapter):
    country_code = "RS"
    country_name = "Serbia"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    API_BASE = "https://openapi.apr.gov.rs"
    COMPANIES_PATH = "/api/opendata/companies"
    FINANCIALS_PATH = "/api/opendata/companies/financial-statements"

    def _client(self, *, timeout: float = 180.0):
        return build_http_client(
            base_url=self.API_BASE,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )

    async def _dataset(self, path: str) -> dict[str, Any]:
        """Fetch and cache an APR open-data snapshot (``{DatumPreseka, Podaci}``)."""
        async with _CACHE_LOCK:
            cached = _CACHE.get(path)
            if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]
            async with self._client() as client:
                resp = await get_with_retry(client, path)
                resp.raise_for_status()
                data = resp.json()
            if not isinstance(data, dict) or not isinstance(data.get("Podaci"), dict):
                raise ValueError(f"Unexpected APR open-data shape for {path}")
            _CACHE[path] = (time.monotonic(), data)
            return data

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client(timeout=20.0) as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
                ok = resp.json().get("title") == "success"
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"APR openapi probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "APR open-data API (openapi.apr.gov.rs): company register + "
                "RGFI financial statements. Bulk JSON snapshots cached in-process; "
                "PIB and per-filing PDFs are not exposed by the free datasets."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        needle = _fold(name.strip())
        if not needle:
            return []
        data = await self._dataset(self.COMPANIES_PATH)
        records: dict[str, Any] = data["Podaci"]
        out: list[CompanyMatch] = []
        for mb, rec in records.items():
            business_name = rec.get("PoslovnoIme") or ""
            if needle not in _fold(business_name):
                continue
            out.append(
                CompanyMatch(
                    id=mb,
                    name=business_name.strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=mb,
                            label="Matični broj",
                        )
                    ],
                    address=rec.get("NazivOpstine"),
                    status=_classify_status(rec.get("NazivStatus")),
                    source_url=self._company_source_url(mb),
                )
            )
            if len(out) >= limit:
                break
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                "Serbia open data resolves COMPANY_NUMBER (Matični broj) only; "
                "PIB is not present in the free APR datasets."
            )
        mb = _normalize_mb(value)
        data = await self._dataset(self.COMPANIES_PATH)
        rec = data["Podaci"].get(mb)
        if rec is None:
            return None
        activity = rec.get("SifraDelatnosti")
        return CompanyDetails(
            id=mb,
            name=(rec.get("PoslovnoIme") or "").strip(),
            country=self.country_code,
            legal_form=rec.get("NazivPravneForme"),
            status=_classify_status(rec.get("NazivStatus")),
            incorporation_date=_parse_rs_date(rec.get("DatumOsnivanja")),
            registered_address=rec.get("NazivOpstine"),
            nace_codes=[str(activity)] if activity else [],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=mb,
                    label="Matični broj",
                )
            ],
            raw={
                "source": "openapi.apr.gov.rs/api/opendata/companies",
                "snapshot": data.get("DatumPreseka"),
                "fields": rec,
            },
            source_url=self._company_source_url(mb),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        mb = _normalize_mb(company_id)
        data = await self._dataset(self.FINANCIALS_PATH)
        rec = data["Podaci"].get(mb)
        if rec is None:
            return []
        year = _as_int(rec.get("GodinaFi"))
        if year is None:
            return []

        net_income: float | None = None
        profit = _to_rsd(rec.get("NetoDobitak"))
        loss = _to_rsd(rec.get("NetoGubitak"))
        if profit is not None or loss is not None:
            net_income = (profit or 0.0) - (loss or 0.0)

        structured: dict[str, Any] = {
            "currency": "RSD",
            "period_end": f"{year}-12-31",
            "balance_sheet": {
                "total_assets": _to_rsd(rec.get("PoslovnaImovina")),
                "total_equity": _to_rsd(rec.get("Kapital")),
            },
            "income_statement": {
                "revenue": _to_rsd(rec.get("UkupniPrihodi")),
                "net_income": net_income,
            },
            "raw_concepts": {
                "source": "openapi.apr.gov.rs RGFI (values in thousands RSD)",
                "snapshot": data.get("DatumPreseka"),
                "average_employees": _as_int(rec.get("ProsecanBrojZaposlenih")),
                **rec,
            },
        }

        return [
            FinancialFiling(
                company_id=mb,
                year=year,
                type=FilingType.ANNUAL_REPORT,
                period_end=date(year, 12, 31),
                currency="RSD",
                structured_data=structured,
                document_url=None,
                document_format="json",
                source_url=f"{self.API_BASE}{self.FINANCIALS_PATH}",
            )
        ]

    def _company_source_url(self, mb: str) -> str:
        return (
            f"{self.API_BASE}{self.COMPANIES_PATH}"
            f"#{quote(mb, safe='')}"
        )
