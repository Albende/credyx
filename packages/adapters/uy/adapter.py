"""Uruguay adapter — RUPE (open-data registry) + BVM (listed-issuer filings).

Sources (both free, no API key, no CAPTCHA):

- **RUPE — Registro Único de Proveedores del Estado**, published as an open
  dataset on the national catalogue `catalogodatos.gub.uy` (CKAN). The CKAN
  ``datastore_search`` action gives a live, queryable index of ~110k
  Uruguayan entities with their RUT (``identificacion_prov``), legal name,
  fiscal address and active/inactive status. Backs both ``search_by_name``
  and ``lookup_by_identifier``.
- **BVM — Bolsa de Valores de Montevideo** (``www.bvm.com.uy``). Each
  registered issuer has a public ``/operadores/documentos/{id}`` page listing
  its filed documents, including audited *Estados Contables* (financial
  statements) as directly-downloadable PDFs. Backs ``fetch_financials``:
  the RUT is resolved to a legal name via RUPE, matched against the BVM
  issuer directory, and that issuer's filed financial-statement PDFs are
  returned with real ``document_url``s — never fabricated line items.

Identifier: **RUT** (Registro Único Tributario) — 12 digits, also the tax ID.
Exposed as both ``VAT`` (primary) and ``COMPANY_NUMBER`` (alias). We accept
any well-formed 12-digit RUT and do not reject on the Mod-11 check digit —
the source registry is the authority.

The former DGI ``JSConsRUTRest`` JSON endpoint was retired (it now 302s to a
dead ``serviciosenlinea`` path) and the DGI web-service RUT lookup requires an
X.509 client certificate, so neither is usable key-free; RUPE replaces it.
"""
from __future__ import annotations

import re
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

_DIGITS_RE = re.compile(r"\D+")
_RUT_RE = re.compile(r"^\d{12}$")
_PERIOD_RE = re.compile(r"al\s+(\d{2})[./](\d{2})[./](\d{4})", re.IGNORECASE)
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _normalize_rut(value: str) -> str:
    raw = (value or "").strip().upper()
    if raw.startswith("UY"):
        raw = raw[2:]
    cleaned = _DIGITS_RE.sub("", raw)
    if not _RUT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Uruguayan RUT must be 12 digits, got: {value!r}"
        )
    return cleaned


class UYAdapter(CountryAdapter):
    country_code = "UY"
    country_name = "Uruguay"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CKAN_BASE = "https://catalogodatos.gub.uy"
    RUPE_DATASET_PREFIX = "registro-unico-de-proveedores-del-estado-rupe"
    BVM_BASE = "https://www.bvm.com.uy"
    BVM_ISSUER_PATHS = (
        "/operadores/emisores-de-acciones",
        "/operadores/emisores-de-obligaciones-negociables",
    )

    _FINANCIAL_MARKERS = (
        "estados contables",
        "estado de situacion",
        "informe anual",
        "memoria anual",
    )

    _rupe_resource: str | None = None

    async def health_check(self) -> AdapterHealth:
        try:
            resource_id = await self._rupe_resource_id()
            async with self._ckan_client() as client:
                resp = await get_with_retry(
                    client,
                    "/api/3/action/datastore_search",
                    params={"resource_id": resource_id, "limit": 1},
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        if resp.status_code >= 500 or not _ckan_ok(resp):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"RUPE datastore returned HTTP {resp.status_code}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search/lookup via RUPE open-data registry; financials via BVM "
                "filed statements (BVM-registered issuers only)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = (name or "").strip()
        if not query:
            return []
        resource_id = await self._rupe_resource_id()
        records = await self._rupe_query(
            {"resource_id": resource_id, "q": query, "limit": max(1, limit)}
        )
        return [_match_from_rupe(r) for r in records if r.get("identificacion_prov")]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"UY only supports VAT/COMPANY_NUMBER (RUT), got {id_type}"
            )
        rut = _normalize_rut(value)
        resource_id = await self._rupe_resource_id()
        records = await self._rupe_query(
            {
                "resource_id": resource_id,
                "filters": f'{{"identificacion_prov":"{rut}"}}',
                "limit": 1,
            }
        )
        if not records:
            return None
        return _details_from_rupe(rut, records[0], resource_id)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        rut = _normalize_rut(company_id)
        details = await self.lookup_by_identifier(IdentifierType.VAT, rut)
        if details is None:
            return []

        issuer_id = await self._bvm_issuer_id(details.name)
        if issuer_id is None:
            return []

        documents = await self._bvm_documents(issuer_id)
        filings: list[FinancialFiling] = []
        seen: set[str] = set()
        for href, filed_on, title in documents:
            classified = _classify_financial(title)
            if classified is None:
                continue
            filing_type, period_end = classified
            year = period_end.year if period_end else (filed_on.year if filed_on else None)
            if year is None:
                continue
            if href in seen:
                continue
            seen.add(href)
            filings.append(
                FinancialFiling(
                    company_id=rut,
                    year=year,
                    type=filing_type,
                    period_end=period_end,
                    currency=None,
                    structured_data=None,
                    document_url=f"{self.BVM_BASE}{href}",
                    document_format="pdf",
                    source_url=f"{self.BVM_BASE}/operadores/documentos/{issuer_id}",
                )
            )

        filings.sort(key=lambda f: (f.year, f.period_end or date(f.year, 1, 1)), reverse=True)
        allowed_years = sorted({f.year for f in filings}, reverse=True)[:years]
        return [f for f in filings if f.year in allowed_years]

    async def _rupe_resource_id(self) -> str:
        if self._rupe_resource:
            return self._rupe_resource
        async with self._ckan_client() as client:
            resp = await get_with_retry(
                client,
                "/api/3/action/package_search",
                params={"q": self.RUPE_DATASET_PREFIX, "rows": 20},
            )
        payload = _json_or_block(resp, "RUPE package_search")
        packages = payload.get("result", {}).get("results", [])
        best_year = -1
        best_resource: str | None = None
        for pkg in packages:
            name = pkg.get("name", "")
            if self.RUPE_DATASET_PREFIX not in name:
                continue
            year_match = re.search(r"(\d{4})$", name)
            year = int(year_match.group(1)) if year_match else 0
            monthly = [
                r
                for r in pkg.get("resources", [])
                if r.get("datastore_active")
                and "proveedores" in (r.get("name") or "").lower()
            ]
            if monthly and year >= best_year:
                best_year = year
                best_resource = monthly[-1]["id"]
        if not best_resource:
            raise BlockedByRegistryError(
                "Could not resolve an active RUPE datastore resource on "
                "catalogodatos.gub.uy."
            )
        self._rupe_resource = best_resource
        return best_resource

    async def _rupe_query(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._ckan_client() as client:
            resp = await get_with_retry(
                client, "/api/3/action/datastore_search", params=params
            )
        payload = _json_or_block(resp, "RUPE datastore_search")
        return payload.get("result", {}).get("records", [])

    async def _bvm_issuer_id(self, company_name: str) -> str | None:
        target = _norm_name(company_name)
        if not target:
            return None
        issuers = await self._bvm_issuers()
        for norm, issuer_id in issuers:
            if norm == target:
                return issuer_id
        for norm, issuer_id in issuers:
            if norm and (norm in target or target in norm):
                return issuer_id
        return None

    async def _bvm_issuers(self) -> list[tuple[str, str]]:
        issuers: list[tuple[str, str]] = []
        async with self._bvm_client() as client:
            for path in self.BVM_ISSUER_PATHS:
                resp = await get_with_retry(client, path)
                if resp.status_code >= 400:
                    continue
                issuers.extend(_parse_bvm_issuers(resp.text))
        return issuers

    async def _bvm_documents(
        self, issuer_id: str
    ) -> list[tuple[str, date | None, str]]:
        async with self._bvm_client() as client:
            resp = await get_with_retry(
                client, f"/operadores/documentos/{issuer_id}"
            )
        if resp.status_code >= 400:
            return []
        return _parse_bvm_documents(resp.text)

    def _ckan_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.CKAN_BASE,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    def _bvm_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BVM_BASE,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-UY,es;q=0.9,en;q=0.7",
            },
            timeout=30.0,
        )


def _ckan_ok(resp: httpx.Response) -> bool:
    try:
        return bool(resp.json().get("success"))
    except ValueError:
        return False


def _json_or_block(resp: httpx.Response, what: str) -> dict[str, Any]:
    if resp.status_code == 403:
        raise BlockedByRegistryError(f"{what} returned 403 (rate limit / geofence).")
    if resp.status_code >= 500:
        raise BlockedByRegistryError(f"{what} returned HTTP {resp.status_code}.")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise BlockedByRegistryError(
            f"{what} returned a non-JSON body (service may be unavailable)."
        ) from exc
    if not payload.get("success"):
        raise BlockedByRegistryError(f"{what} reported an unsuccessful response.")
    return payload


def _match_from_rupe(record: dict[str, Any]) -> CompanyMatch:
    rut = str(record["identificacion_prov"]).strip()
    id_type = IdentifierType.VAT if _RUT_RE.match(rut) else IdentifierType.OTHER
    return CompanyMatch(
        id=rut,
        name=(record.get("denominacion_social_prov") or rut).strip(),
        country="UY",
        identifiers=[RegistryIdentifier(type=id_type, value=rut, label="RUT")],
        address=_compose_address(record),
        status=(record.get("estado_prov") or None),
        source_url=f"{UYAdapter.CKAN_BASE}/dataset",
    )


def _details_from_rupe(
    rut: str, record: dict[str, Any], resource_id: str
) -> CompanyDetails:
    name = (record.get("denominacion_social_prov") or rut).strip()
    identifiers = [
        RegistryIdentifier(type=IdentifierType.VAT, value=rut, label="RUT"),
        RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=rut, label="RUT"),
    ]
    return CompanyDetails(
        id=rut,
        name=name,
        country="UY",
        status=(record.get("estado_prov") or None),
        registered_address=_compose_address(record),
        identifiers=identifiers,
        raw=dict(record),
        source_url=(
            f"{UYAdapter.CKAN_BASE}/api/3/action/datastore_search"
            f"?resource_id={resource_id}"
            f'&filters={{"identificacion_prov":"{rut}"}}'
        ),
    )


def _compose_address(record: dict[str, Any]) -> str | None:
    parts = [
        record.get("domicilio_fiscal"),
        record.get("localidad_prov"),
        record.get("departamento_prov"),
        record.get("pais_prov"),
    ]
    cleaned = [str(p).strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


_BVM_ISSUER_RE = re.compile(
    r"<h4>(?P<name>.*?)</h4>.*?/operadores/documentos/(?P<id>\d+)",
    re.IGNORECASE | re.DOTALL,
)
_BVM_DOC_RE = re.compile(
    r'href="(?P<href>/repo/arch/[^"]+\.pdf)".*?'
    r'fechaDoc">(?P<fecha>\d{2}/\d{2}/\d{4}).*?'
    r'textoDoc">(?P<texto>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)


def _parse_bvm_issuers(html: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _BVM_ISSUER_RE.finditer(html):
        name = _unescape(m.group("name"))
        out.append((_norm_name(name), m.group("id")))
    return out


def _parse_bvm_documents(html: str) -> list[tuple[str, date | None, str]]:
    out: list[tuple[str, date | None, str]] = []
    for m in _BVM_DOC_RE.finditer(html):
        filed_on = _parse_dmy(m.group("fecha"))
        title = _unescape(m.group("texto"))
        out.append((m.group("href"), filed_on, title))
    return out


def _classify_financial(title: str) -> tuple[FilingType, date | None] | None:
    norm = _strip_accents(title).lower()
    if not any(marker in norm for marker in UYAdapter._FINANCIAL_MARKERS):
        return None
    period_end = None
    period_match = _PERIOD_RE.search(title)
    if period_match:
        day, month, year = (int(g) for g in period_match.groups())
        try:
            period_end = date(year, month, day)
        except ValueError:
            period_end = None
    if "estados contables" in norm or "estado de situacion" in norm:
        return FilingType.BALANCE_SHEET, period_end
    return FilingType.ANNUAL_REPORT, period_end


def _norm_name(value: str) -> str:
    s = _strip_accents(value or "").upper()
    s = re.sub(r"\bSOCIEDAD ANONIMA( CERRADA)?\b", "SA", s)
    s = re.sub(r"\bSOCIEDAD DE RESPONSABILIDAD LIMITADA\b", "SRL", s)
    s = re.sub(r"\bSOCIEDAD POR ACCIONES SIMPLIFICADA\b", "SAS", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def _strip_accents(value: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(c)
    )


def _unescape(value: str) -> str:
    import html as _html

    return _html.unescape(re.sub(r"\s+", " ", value)).strip()


def _parse_dmy(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None
