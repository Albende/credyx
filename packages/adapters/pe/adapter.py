"""Peru adapter — BVL / SMV listed-company data (dataondemand API).

The Peruvian corporate register that credit analysis actually wants is
SUNAT's RUC verifier, but that endpoint is now fronted by an invisible
reCAPTCHA v3 challenge (``site_key_sunat`` / action ``consultaRUC01``) and
resets raw connections, so it cannot be read key-free. Community RUC
wrappers (apis.net.pe, decolecta, apiperu, migo) are all token-gated. Per
the no-mock-data rule we do not fabricate around that block — see
``docs/countries/pe.md``.

The only free, key-less, live source of real per-company data for Peru is
the **Bolsa de Valores de Lima** "data on demand" API, which the SMV
(securities regulator) feeds. It is public and needs no key:

- ``GET /v1/issuers`` — every listed/registered issuer with sector,
  address, website, tickers (nemónicos/ISINs) and the list of filed
  annual documents (``listMemoryEEFF``: Memoria Anual, Estados
  Financieros, etc.).
- ``GET /v1/issuers/{companyCode}`` — a single issuer record.
- ``GET /v1/financial-statements/{rpjCode}`` — the issuer's audited
  financial ratios (liquidity, solvency, debt/equity, ROE, asset
  turnover, book value) per year.

Identifier: BVL/SMV uses two codes, not the RUC. The **companyCode** is the
short numeric BVL code (e.g. ``61200``); the **rpjCode** is the SMV
"Registro Público del Mercado de Valores" code (e.g. ``B20003``). We expose
the companyCode as the primary ``COMPANY_NUMBER`` and accept the rpjCode or
a ticker as an alias. RUC is not carried by this source, so lookups are by
BVL/SMV code — resolve one from a name via :meth:`PEAdapter.search_by_name`.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    BlockedByRegistryError,
    InvalidIdentifierError,
)
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


def _fold(value: str) -> str:
    """Uppercase and strip accents for accent-insensitive name matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.upper().strip()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class PEAdapter(CountryAdapter):
    country_code = "PE"
    country_name = "Peru"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.OTHER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BVL_BASE = "https://dataondemand.bvl.com.pe"

    # Compañía de Minas Buenaventura — stable BVL canary for health probes.
    _HEALTH_CODE = "61200"

    def __init__(self) -> None:
        self._issuers: list[dict[str, Any]] | None = None

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client, f"/v1/issuers/{self._HEALTH_CODE}"
                )
        except Exception as exc:  # noqa: BLE001 — boundary
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=f"BVL returned HTTP {resp.status_code}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Source: BVL/SMV dataondemand API (listed & registered issuers). "
                "SUNAT RUC lookup is reCAPTCHA-v3 walled and not used."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = _fold(name)
        if not needle:
            return []
        issuers = await self._all_issuers()
        matches: list[CompanyMatch] = []
        for row in issuers:
            folded = _fold(row.get("companyName") or "")
            if needle not in folded:
                continue
            matches.append(self._to_match(row))
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.OTHER):
            raise InvalidIdentifierError(
                f"PE supports COMPANY_NUMBER (BVL companyCode) or OTHER "
                f"(SMV rpjCode / ticker), got {id_type}"
            )
        row = await self._resolve_issuer(value)
        if row is None:
            return None
        return self._to_details(row)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        row = await self._resolve_issuer(company_id)
        if row is None:
            return []
        rpj = _clean(row.get("rpjCode"))
        if not rpj:
            return []

        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client, f"/v1/financial-statements/{rpj}"
                )
        except httpx.HTTPError as exc:
            raise BlockedByRegistryError(
                f"BVL financial-statements transport error for {rpj}: {exc}"
            ) from exc
        if resp.status_code >= 500:
            raise BlockedByRegistryError(
                f"BVL returned HTTP {resp.status_code} for {rpj}"
            )
        if resp.status_code == 404:
            return []

        ratio_rows = resp.json() or []
        by_year: dict[int, dict[str, Any]] = {}
        for ratio in ratio_rows:
            label = _clean(ratio.get("dRatio"))
            if not label:
                continue
            for point in ratio.get("finantialIndexYears") or []:
                yr_raw = point.get("year")
                val = point.get("nImporteA")
                if yr_raw is None or val is None:
                    continue
                try:
                    yr = int(str(yr_raw)[:4])
                except ValueError:
                    continue
                by_year.setdefault(yr, {})[label] = self._to_float(val)

        if not by_year:
            return []

        code = _clean(row.get("companyCode")) or rpj
        source_url = f"{self.BVL_BASE}/v1/financial-statements/{rpj}"
        docs_by_year = self._eeff_docs_by_year(row)

        filings: list[FinancialFiling] = []
        for yr in sorted(by_year, reverse=True)[:years]:
            structured = {"bvl_financial_ratios": by_year[yr]}
            doc = docs_by_year.get(yr)
            if doc:
                structured["bvl_document"] = doc
            filings.append(
                FinancialFiling(
                    company_id=code,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="PEN",
                    structured_data=structured,
                    document_url=None,
                    document_format="json",
                    source_url=source_url,
                )
            )
        return filings

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BVL_BASE,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    async def _all_issuers(self) -> list[dict[str, Any]]:
        if self._issuers is not None:
            return self._issuers
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, "/v1/issuers")
        except httpx.HTTPError as exc:
            raise BlockedByRegistryError(
                f"BVL issuers list transport error: {exc}"
            ) from exc
        if resp.status_code >= 500:
            raise BlockedByRegistryError(
                f"BVL returned HTTP {resp.status_code} for issuers list"
            )
        self._issuers = resp.json() or []
        return self._issuers

    async def _resolve_issuer(self, value: str) -> dict[str, Any] | None:
        key = (value or "").strip()
        if not key:
            raise InvalidIdentifierError("PE identifier must not be empty")

        if key.isdigit():
            try:
                async with self._client() as client:
                    resp = await get_with_retry(client, f"/v1/issuers/{key}")
            except httpx.HTTPError as exc:
                raise BlockedByRegistryError(
                    f"BVL issuer lookup transport error for {key}: {exc}"
                ) from exc
            if resp.status_code == 404:
                return None
            if resp.status_code >= 500:
                raise BlockedByRegistryError(
                    f"BVL returned HTTP {resp.status_code} for {key}"
                )
            body = resp.json()
            if isinstance(body, dict) and body.get("companyCode"):
                return body
            if isinstance(body, list) and body:
                return body[0]
            return None

        folded = key.upper()
        for row in await self._all_issuers():
            if (
                _clean(row.get("rpjCode")) == folded
                or _clean(row.get("companyCode")) == folded
                or any(
                    (_clean(v.get("nemonico")) or "").upper() == folded
                    for v in row.get("listValue") or []
                )
            ):
                return row
        return None

    def _to_match(self, row: dict[str, Any]) -> CompanyMatch:
        return CompanyMatch(
            id=_clean(row.get("companyCode")) or _clean(row.get("rpjCode")) or "",
            name=_clean(row.get("companyName")) or "",
            country="PE",
            identifiers=self._identifiers(row),
            address=_clean(row.get("companyAddress")),
            status="active" if row.get("active") else "inactive",
            source_url=f"{self.BVL_BASE}/v1/issuers/{_clean(row.get('companyCode'))}",
        )

    def _to_details(self, row: dict[str, Any]) -> CompanyDetails:
        code = _clean(row.get("companyCode")) or _clean(row.get("rpjCode")) or ""
        website = _clean(row.get("website"))
        if website and not website.lower().startswith("http"):
            website = f"http://{website}"
        return CompanyDetails(
            id=code,
            name=_clean(row.get("companyName")) or code,
            country="PE",
            legal_form=_clean(row.get("description")),
            status="active" if row.get("active") else "inactive",
            incorporation_date=self._parse_date(row.get("dateFundation")),
            registered_address=_clean(row.get("companyAddress")),
            nace_codes=[c for c in (_clean(row.get("subSectorCode")),) if c],
            identifiers=self._identifiers(row),
            website=website,
            phone=_clean(row.get("phone")),
            raw={
                "companyCode": _clean(row.get("companyCode")),
                "rpjCode": _clean(row.get("rpjCode")),
                "sectorCode": _clean(row.get("sectorCode")),
                "sector": _clean(row.get("description")),
                "subSectorCode": _clean(row.get("subSectorCode")),
                "tickers": [
                    _clean(v.get("nemonico"))
                    for v in row.get("listValue") or []
                    if _clean(v.get("nemonico"))
                ],
                "source": "bvl.dataondemand",
            },
            source_url=f"{self.BVL_BASE}/v1/issuers/{_clean(row.get('companyCode'))}",
        )

    @staticmethod
    def _identifiers(row: dict[str, Any]) -> list[RegistryIdentifier]:
        ids: list[RegistryIdentifier] = []
        code = _clean(row.get("companyCode"))
        if code:
            ids.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=code,
                    label="BVL companyCode",
                )
            )
        rpj = _clean(row.get("rpjCode"))
        if rpj:
            ids.append(
                RegistryIdentifier(
                    type=IdentifierType.OTHER, value=rpj, label="SMV rpjCode"
                )
            )
        for v in row.get("listValue") or []:
            nem = _clean(v.get("nemonico"))
            if nem:
                ids.append(
                    RegistryIdentifier(
                        type=IdentifierType.OTHER, value=nem, label="ticker"
                    )
                )
        return ids

    @staticmethod
    def _eeff_docs_by_year(row: dict[str, Any]) -> dict[int, dict[str, Any]]:
        docs: dict[int, dict[str, Any]] = {}
        for entry in row.get("listMemoryEEFF") or []:
            document = _clean(entry.get("document")) or ""
            if "memoria anual" not in document.lower():
                continue
            yr_raw = entry.get("year")
            if yr_raw is None:
                continue
            try:
                yr = int(str(yr_raw)[:4])
            except ValueError:
                continue
            docs.setdefault(
                yr,
                {"document": document, "path": _clean(entry.get("path"))},
            )
        return docs

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        text = _clean(value)
        if not text:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None
