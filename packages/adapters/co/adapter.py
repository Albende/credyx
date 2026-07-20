"""Colombia adapter — RUES (registry) + Supersociedades (financials).

Sources:

* RUES — Registro Único Empresarial y Social, operated by CONFECAMARAS
  (the umbrella body for Colombia's chambers of commerce). Public, free,
  no auth. The modernised backend exposes two JSON services:
  - ``https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM``
    (POST) — advanced search over the mercantile register by ``razon``
    (name) or ``nit``. Returns summary records keyed by ``id_rm``.
  - ``https://ruesapi.rues.org.co/WEB2/api/Expediente/DetalleRM/{id_rm}``
    (GET) — the full expediente for one register entry (address, CIIU,
    dates, legal form, tax id + check digit).
  Both hosts reject non-browser clients with a bare ``403``; we send a
  browser ``User-Agent`` + ``Origin`` / ``Referer`` (the same headers the
  public portal sends) and parse the JSON directly.

* Supersociedades — the Superintendencia de Sociedades publishes the NIIF
  (IFRS) financial statements every non-financial company is legally
  required to file, as open data on ``datos.gov.co`` (Socrata / SODA API,
  no key required). Four datasets, joined by ``codigo_instancia``:
  ``pfdp-zks5`` (statement of financial position), ``prwj-nzxa`` (income
  statement), ``ctcp-462n`` (cash flow), ``y3gh-x5g7`` (OCI). We map the
  filed line items into the unified ``structured_data`` schema the risk
  engine consumes, per year, entity-level (non-consolidated) statements
  preferred.

Identifier — NIT (Número de Identificación Tributaria), the DIAN-issued
tax + corporate id. 9–10 body digits plus a single check digit, displayed
as ``XXX.XXX.XXX-D``. Exposed as both ``VAT`` (primary) and
``COMPANY_NUMBER``.

No-mock-data rule: RUES and Supersociedades are the only sources. SFC-
supervised entities (banks, insurers, listed issuers) report to the
Superintendencia Financiera, not Supersociedades, so ``fetch_financials``
returns ``[]`` for them rather than fabricate figures. If a source's shape
changes so it can't be parsed, we raise — never invent.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client
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

_DIGITS_RE = re.compile(r"\D+")
_NIT_BODY_RE = re.compile(r"^\d{9,10}$")

# DIAN check-digit weights, applied right-to-left to the NIT body (without
# the trailing check digit). The published table goes up to 15 positions; we
# only ever consume the rightmost 9 or 10.
_NIT_WEIGHTS = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]

# Ecopetrol — a stable, always-active anchor for liveness probes.
_HEALTH_PROBE_NIT = "899999068"

# The RUES hosts 403 any client without the portal's browser headers.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.7",
    "Origin": "https://www.rues.org.co",
    "Referer": "https://www.rues.org.co/",
}


class COAdapter(CountryAdapter):
    country_code = "CO"
    country_name = "Colombia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    RUES_SEARCH_URL = (
        "https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM"
    )
    RUES_DETAIL_URL = "https://ruesapi.rues.org.co/WEB2/api/Expediente/DetalleRM/{id_rm}"

    # Supersociedades NIIF financial statements, open data on datos.gov.co.
    SODA_BASE = "https://www.datos.gov.co/resource"
    DS_BALANCE = "pfdp-zks5"
    DS_INCOME = "prwj-nzxa"
    DS_CASHFLOW = "ctcp-462n"
    SODA_DATASET_URL = "https://www.datos.gov.co/d/{ds}"

    def _rues_client(self) -> httpx.AsyncClient:
        return build_http_client(headers=_BROWSER_HEADERS, timeout=30.0)

    def _soda_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.SODA_BASE,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._rues_client() as client:
                records = await _rues_search(client, {"nit": _HEALTH_PROBE_NIT})
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
        reachable = any(r.get("nit") == _HEALTH_PROBE_NIT for r in records)
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if reachable else AdapterStatus.ERROR,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "RUES BusquedaAvanzadaRM + DetalleRM for registry; "
                "Supersociedades NIIF filings (datos.gov.co) for financials. "
                "SFC-supervised entities report to SuperFinanciera and return "
                "no Supersociedades filings."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not name or not name.strip():
            return []
        async with self._rues_client() as client:
            records = await _rues_search(client, {"razon": name.strip()})
            ranked = sorted(records, key=_principal_rank)
            id_rms = [r["id_rm"] for r in ranked if r.get("id_rm")][: max(limit * 2, limit)]
            details = await asyncio.gather(
                *(_rues_detail(client, id_rm) for id_rm in id_rms),
                return_exceptions=True,
            )

        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for detail in details:
            if isinstance(detail, BaseException) or not detail:
                continue
            nit_body = _detail_nit(detail)
            if not nit_body or nit_body in seen:
                continue
            seen.add(nit_body)
            matches.append(_match_from_detail(nit_body, detail, self.country_code))
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"CO only supports VAT/COMPANY_NUMBER (NIT), got {id_type}"
            )
        nit_body, supplied_check = _normalize_nit(value)
        if supplied_check is not None:
            expected = _nit_check_digit(nit_body)
            if supplied_check != expected:
                raise InvalidIdentifierError(
                    f"NIT check digit invalid for {value} "
                    f"(expected {expected}, got {supplied_check})"
                )

        async with self._rues_client() as client:
            records = await _rues_search(client, {"nit": nit_body})
            record = _principal_for_nit(records, nit_body)
            if record is None:
                return None
            detail = await _rues_detail(client, record["id_rm"])
        if not detail:
            return None
        return _details_from_detail(nit_body, detail, self.country_code)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        nit_body, _ = _normalize_nit(company_id)
        async with self._soda_client() as client:
            rows = await asyncio.gather(
                _soda_rows(client, self.DS_BALANCE, nit_body),
                _soda_rows(client, self.DS_INCOME, nit_body),
                _soda_rows(client, self.DS_CASHFLOW, nit_body),
            )

        instances = _group_instances(rows)
        if not instances:
            return []

        chosen = _select_annual_instances(instances, years)
        filings: list[FinancialFiling] = []
        for inst in chosen:
            structured = _structured_from_instance(inst)
            if not any(structured.get(s) for s in ("balance_sheet", "income_statement", "cash_flow")):
                continue
            corte = inst["fecha_corte"]
            doc_url = (
                f"{self.SODA_BASE}/{self.DS_BALANCE}.json"
                f"?nit={nit_body}&fecha_corte={corte}"
            )
            filings.append(
                FinancialFiling(
                    company_id=nit_body,
                    year=inst["year"],
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(inst["year"], 12, 31),
                    currency="COP",
                    structured_data=structured,
                    document_url=doc_url,
                    document_format="json",
                    source_url=self.SODA_DATASET_URL.format(ds=self.DS_BALANCE),
                )
            )
        return filings


async def _rues_search(
    client: httpx.AsyncClient, payload: dict[str, str]
) -> list[dict[str, Any]]:
    resp = await _post_with_retry(client, COAdapter.RUES_SEARCH_URL, payload)
    if resp.status_code in (204, 404):
        return []
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as exc:
        raise AdapterNotImplementedError(
            "RUES search returned non-JSON; see docs/countries/co.md."
        ) from exc
    if not isinstance(data, dict) or "registros" not in data:
        raise AdapterNotImplementedError(
            "RUES search response shape changed; see docs/countries/co.md."
        )
    registros = data.get("registros")
    if registros is None:
        return []
    if not isinstance(registros, list):
        raise AdapterNotImplementedError(
            "RUES search 'registros' was not a list; see docs/countries/co.md."
        )
    return [r for r in registros if isinstance(r, dict)]


async def _rues_detail(
    client: httpx.AsyncClient, id_rm: str
) -> dict[str, Any] | None:
    resp = await client.get(COAdapter.RUES_DETAIL_URL.format(id_rm=id_rm))
    if resp.status_code in (204, 404):
        return None
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return None
    registros = data.get("registros")
    if isinstance(registros, dict):
        return registros
    return None


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    json_body: dict[str, str],
    *,
    max_attempts: int = 3,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.post(url, json=json_body)
            if resp.status_code == 429:
                await asyncio.sleep(float(resp.headers.get("Retry-After", 5)))
                continue
            return resp
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            await asyncio.sleep(0.8 * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


async def _soda_rows(
    client: httpx.AsyncClient, dataset: str, nit_body: str
) -> list[dict[str, Any]]:
    params = {
        "nit": nit_body,
        "periodo": "Periodo Actual",
        "$limit": "10000",
    }
    resp = await client.get(f"/{dataset}.json", params=params)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _normalize_nit(value: str) -> tuple[str, str | None]:
    """Return (body, supplied_check_digit_or_None).

    Accepts strings like ``"899.999.068-1"``, ``"CO 899999068-1"``,
    ``"899999068"``, or ``"8999990681"``. Raises on anything else.
    """
    if value is None:
        raise InvalidIdentifierError("NIT is required")
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned.startswith("CO"):
        cleaned = cleaned[2:]
    body: str
    check: str | None
    if "-" in cleaned:
        body_raw, _, tail = cleaned.rpartition("-")
        body = _DIGITS_RE.sub("", body_raw)
        check_digits = _DIGITS_RE.sub("", tail)
        if len(check_digits) != 1:
            raise InvalidIdentifierError(
                f"NIT check digit segment must be a single digit: {value}"
            )
        check = check_digits
    else:
        digits = _DIGITS_RE.sub("", cleaned)
        if len(digits) == 11:
            body = digits[:-1]
            check = digits[-1]
        else:
            body = digits
            check = None
    if not _NIT_BODY_RE.match(body):
        raise InvalidIdentifierError(
            f"NIT body must be 9 or 10 digits, got '{body}' from '{value}'"
        )
    return body, check


def _nit_check_digit(body: str) -> str:
    total = 0
    for idx, digit in enumerate(reversed(body)):
        if idx >= len(_NIT_WEIGHTS):
            break
        total += int(digit) * _NIT_WEIGHTS[idx]
    rem = total % 11
    if rem < 2:
        return str(rem)
    return str(11 - rem)


def _principal_rank(rec: dict[str, Any]) -> int:
    categoria = (rec.get("categoria") or "").upper()
    return 0 if "PRINCIPAL" in categoria else 1


def _principal_for_nit(
    records: list[dict[str, Any]], nit_body: str
) -> dict[str, Any] | None:
    candidates = [
        r for r in records if _digits(r.get("nit")) == nit_body and r.get("id_rm")
    ]
    if not candidates:
        return None
    candidates.sort(key=_principal_rank)
    return candidates[0]


def _digits(value: Any) -> str:
    if value is None:
        return ""
    return _DIGITS_RE.sub("", str(value))


def _detail_nit(detail: dict[str, Any]) -> str | None:
    raw = detail.get("numero_identificacion") or detail.get("numero_identificacion_2")
    digits = _digits(raw).lstrip("0")
    if 9 <= len(digits) <= 10:
        return digits
    return None


def _detail_dv(detail: dict[str, Any], nit_body: str) -> str:
    dv = _digits(detail.get("dv"))
    if len(dv) == 1:
        return dv
    return _nit_check_digit(nit_body)


def _formatted_nit(detail: dict[str, Any], nit_body: str) -> str:
    return f"{nit_body}-{_detail_dv(detail, nit_body)}"


def _pick(rec: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = rec.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _identifiers(formatted: str) -> list[RegistryIdentifier]:
    return [
        RegistryIdentifier(type=IdentifierType.VAT, value=formatted, label="NIT"),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=formatted, label="NIT"
        ),
    ]


def _compose_address(rec: dict[str, Any]) -> str | None:
    parts = [
        _pick(rec, "dir_comercial", "dir_fiscal"),
        _pick(rec, "mun_comercial", "mun_fiscal"),
    ]
    cleaned = [p for p in parts if p]
    return ", ".join(cleaned) if cleaned else None


def _ciiu_codes(rec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in (
        "cod_ciiu_act_econ_pri",
        "cod_ciiu_act_econ_sec",
        "ciiu3",
        "ciiu4",
    ):
        digits = _digits(rec.get(key))
        if digits and digits not in out:
            out.append(digits)
    return out


def _detail_source_url(detail: dict[str, Any]) -> str:
    id_rm = _pick(detail, "id") or ""
    return COAdapter.RUES_DETAIL_URL.format(id_rm=id_rm)


def _match_from_detail(
    nit_body: str, detail: dict[str, Any], country_code: str
) -> CompanyMatch:
    name = _pick(detail, "razon_social") or nit_body
    return CompanyMatch(
        id=nit_body,
        name=name,
        country=country_code,
        identifiers=_identifiers(_formatted_nit(detail, nit_body)),
        address=_compose_address(detail),
        status=_pick(detail, "estado", "estado_matricula", "motivo_cancelacion"),
        source_url=_detail_source_url(detail),
    )


def _details_from_detail(
    nit_body: str, detail: dict[str, Any], country_code: str
) -> CompanyDetails:
    return CompanyDetails(
        id=nit_body,
        name=_pick(detail, "razon_social") or nit_body,
        country=country_code,
        legal_form=_pick(detail, "organizacion_juridica", "tipo_sociedad"),
        status=_pick(detail, "estado", "estado_matricula", "motivo_cancelacion"),
        incorporation_date=_parse_co_date(_pick(detail, "fecha_matricula")),
        registered_address=_compose_address(detail),
        capital_amount=None,
        capital_currency="COP",
        nace_codes=_ciiu_codes(detail),
        identifiers=_identifiers(_formatted_nit(detail, nit_body)),
        raw=dict(detail),
        source_url=_detail_source_url(detail),
    )


def _parse_co_date(value: str | None) -> date | None:
    if not value:
        return None
    s = value.strip()
    if s.isdigit() and len(s) == 8:
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


# --- Supersociedades NIIF concept mapping -----------------------------------

def _skeleton(concept: str) -> str:
    """ASCII skeleton of a filed concept label.

    Supersociedades' published data corrupts many accented characters to
    U+FFFD inconsistently, so we drop every non-``[a-z0-9 ]`` character
    (accents, U+FFFD, punctuation alike) and collapse whitespace. Applied
    identically to the data and to the map keys below so both sides fold
    the same way regardless of how the accent survived ingestion.
    """
    lowered = concept.lower()
    ascii_only = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", ascii_only).strip()


# Filed NIIF concept label -> (unified section, unified key). Entity-level
# NIIF Plenas / Pymes line items as filed with Supersociedades; matched via
# the ASCII skeleton above.
_CONCEPT_MAP: dict[str, tuple[str, str]] = {
    "total de activos": ("balance_sheet", "total_assets"),
    "activos corrientes totales": ("balance_sheet", "current_assets"),
    "total de activos no corrientes": ("balance_sheet", "non_current_assets"),
    "efectivo y equivalentes al efectivo": ("balance_sheet", "cash_and_equivalents"),
    "inventarios corrientes": ("balance_sheet", "inventories"),
    "cuentas comerciales por cobrar y otras cuentas por cobrar corrientes": (
        "balance_sheet",
        "trade_receivables",
    ),
    "total pasivos": ("balance_sheet", "total_liabilities"),
    "pasivos corrientes totales": ("balance_sheet", "current_liabilities"),
    "total de pasivos no corrientes": ("balance_sheet", "non_current_liabilities"),
    "patrimonio total": ("balance_sheet", "total_equity"),
    "capital emitido": ("balance_sheet", "share_capital"),
    "ganancias acumuladas": ("balance_sheet", "retained_earnings"),
    "ingresos de actividades ordinarias": ("income_statement", "revenue"),
    "ganancia bruta": ("income_statement", "gross_profit"),
    "ganancia (pérdida) por actividades de operación": (
        "income_statement",
        "operating_profit",
    ),
    "ganancia (pérdida)": ("income_statement", "net_income"),
    "costos financieros": ("income_statement", "interest_expense"),
    "flujos de efectivo netos procedentes de (utilizados en) actividades de operación": (
        "cash_flow",
        "operating_cf",
    ),
    "flujos de efectivo netos procedentes de (utilizados en) actividades de inversión": (
        "cash_flow",
        "investing_cf",
    ),
    "flujos de efectivo netos procedentes de (utilizados en) actividades de financiación": (
        "cash_flow",
        "financing_cf",
    ),
}

# Map keys folded through the same skeleton used on the incoming data.
_CONCEPT_LOOKUP: dict[str, tuple[str, str]] = {
    _skeleton(label): target for label, target in _CONCEPT_MAP.items()
}


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _group_instances(
    rows_per_dataset: tuple[list[dict[str, Any]], ...]
) -> dict[str, dict[str, Any]]:
    """Merge the three SODA datasets into one record per ``codigo_instancia``.

    Each instance is a single filed statement set (one taxonomy /
    punto_entrada). Only annual (Dec-31) filings are kept.
    """
    instances: dict[str, dict[str, Any]] = {}
    for rows in rows_per_dataset:
        for row in rows:
            corte = str(row.get("fecha_corte") or "")
            if corte[5:10] != "12-31":
                continue
            code = str(row.get("codigo_instancia") or "")
            if not code:
                continue
            inst = instances.get(code)
            if inst is None:
                inst = {
                    "year": int(corte[:4]),
                    "fecha_corte": corte,
                    "punto_entrada": str(row.get("punto_entrada") or ""),
                    "concepts": {},
                }
                instances[code] = inst
            mapped = _CONCEPT_LOOKUP.get(_skeleton(str(row.get("concepto") or "")))
            if mapped is None:
                continue
            number = _to_number(row.get("valor"))
            if number is None:
                continue
            inst["concepts"].setdefault(mapped, number)
    return instances


def _select_annual_instances(
    instances: dict[str, dict[str, Any]], years: int
) -> list[dict[str, Any]]:
    by_year: dict[int, dict[str, Any]] = {}
    for inst in instances.values():
        year = inst["year"]
        current = by_year.get(year)
        if current is None or _instance_rank(inst) > _instance_rank(current):
            by_year[year] = inst
    ordered = [by_year[y] for y in sorted(by_year, reverse=True)]
    return ordered[:years]


def _instance_rank(inst: dict[str, Any]) -> tuple[int, int]:
    """Prefer entity-level (non-consolidated) and more-complete filings."""
    consolidated = "consolidad" in inst["punto_entrada"].lower()
    return (0 if consolidated else 1, len(inst["concepts"]))


def _structured_from_instance(inst: dict[str, Any]) -> dict[str, Any]:
    sections: dict[str, dict[str, float]] = {
        "balance_sheet": {},
        "income_statement": {},
        "cash_flow": {},
    }
    for (section, key), value in inst["concepts"].items():
        sections[section][key] = value
    result: dict[str, Any] = {
        "currency": "COP",
        "units": "thousands",
        "basis": inst["punto_entrada"],
        "source": "Supersociedades (datos.gov.co)",
    }
    for section, values in sections.items():
        if values:
            result[section] = values
    return result


__all__ = [
    "COAdapter",
    # Exposed for unit tests.
    "_normalize_nit",
    "_nit_check_digit",
]
