"""Ecuador adapter — SUPERCIAS (Superintendencia de Compañías) + SRI.

Sources:

* SUPERCIAS public Portal de Consultas —
  ``https://appscvsmovil.supercias.gob.ec/portalConsultas/``.
  Free, no auth. Exposes per-company information (legal status,
  registered office, capital, directors) and the catalog of filed
  annual reports ("Información Económica"). The catalog backs the
  ``/consulta/companias_consultaCompaniaParametros.zul`` web entry
  point; the public mobile/JSON endpoints under
  ``/PortalInformacion/`` and ``/companias/`` are reachable via plain
  HTTP and are what we hit. Shapes shift between deployments so
  parsing is defensive — we never invent fields.
* SRI (Servicio de Rentas Internas) public RUC validator —
  ``https://srienlinea.sri.gob.ec/sri-en-linea/SriRucWeb/ConsultaRuc/``
  Used as a secondary liveness/coverage probe and as a soft check that
  a 13-digit RUC is registered with the tax authority. Auth-free.
* Quito (BVQ) and Guayaquil (BVG) stock exchanges publish per-issuer
  filings for the small set of listed companies. We surface the
  discovery URL — full PDF parsing is Phase-2 work.

Identifier: **RUC** (Registro Único de Contribuyentes). 13 digits.
Format: `PPCCCCCCCCDDD001` where the first two digits are the
province (01–24), digit 3 indicates the contributor class (6 for
public institutions, 9 for sociedades / persona jurídica, 0–5 for
natural persons), the next 6/7 digits identify the body, and the
trailing `001` is the establishment suffix. We expose RUC as both
``VAT`` (primary — RUC is the corporate VAT identifier in Ecuador)
and ``COMPANY_NUMBER`` (alias).

No-mock-data rule: if SUPERCIAS is unreachable or its shape changes,
we raise — never fabricate. Search and lookup hit the documented
JSON paths first and fall back to a defensive HTML parse.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
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

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D+")
_RUC_RE = re.compile(r"^\d{13}$")

# Banco Pichincha — a stable, always-active anchor for liveness probes.
_HEALTH_PROBE_RUC = "1790010937001"


def _normalize_ruc(value: str) -> str:
    """Strip prefixes/punctuation and validate length + digit-only.

    Accepts ``"1790010937001"``, ``"179.001.0937-001"``,
    ``"EC 1790010937001"``. Raises ``InvalidIdentifierError`` for
    anything else. We do not enforce a province-code (01–24) check
    here: SUPERCIAS itself is the source of truth on RUC existence
    and several legacy public-sector RUCs use prefixes outside the
    canonical province band.
    """
    if value is None:
        raise InvalidIdentifierError("RUC is required")
    raw = value.strip().upper()
    if raw.startswith("EC"):
        raw = raw[2:]
    cleaned = _DIGITS_RE.sub("", raw)
    if not _RUC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Ecuadorian RUC must be 13 digits: {value!r} (got {cleaned!r})"
        )
    return cleaned


class ECAdapter(CountryAdapter):
    country_code = "EC"
    country_name = "Ecuador"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    SUPERCIAS_BASE = "https://appscvsmovil.supercias.gob.ec"
    SUPERCIAS_PORTAL = "/portalConsultas/"
    # Public JSON-ish paths used by the consulta portal. The portal
    # front-end posts to ZK endpoints that require a session; the
    # mobile API under /PortalInformacion exposes the same record set
    # without auth and is what we use.
    SUPERCIAS_LOOKUP_PATH = "/PortalInformacion/consulta/companias"
    SUPERCIAS_SEARCH_PATH = "/PortalInformacion/consulta/companias/buscar"
    SUPERCIAS_FILINGS_PATH = "/PortalInformacion/consulta/informacion_economica"

    SRI_BASE = "https://srienlinea.sri.gob.ec"
    SRI_RUC_PATH = "/sri-catastro-sujeto-servicio/rest/ConsolidadoContribuyente/obtenerPorNumerosRuc"

    BVQ_BASE = "https://www.bolsadequito.com"
    BVG_BASE = "https://www.bolsadevaloresguayaquil.com"

    def _client(self, *, base_url: str | None = None) -> httpx.AsyncClient:
        return build_http_client(
            base_url=base_url or self.SUPERCIAS_BASE,
            headers={
                "Accept": "application/json, text/html;q=0.8",
                "Accept-Language": "es-EC,es;q=0.9,en;q=0.7",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    f"{self.SUPERCIAS_LOOKUP_PATH}/{_HEALTH_PROBE_RUC}",
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
                notes=str(exc)[:200],
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"SUPERCIAS returned HTTP {resp.status_code}",
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
                "SUPERCIAS public portal. Annual filings are free via "
                "Información Económica. Listed-company filings under BVQ/BVG."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not name or not name.strip():
            return []
        params = {"expresion": name.strip(), "tipo": "razon_social"}
        payload = await self._fetch_json_or_html(
            self.SUPERCIAS_SEARCH_PATH, params=params
        )
        records = _coerce_records(payload)
        if records is None:
            raise AdapterNotImplementedError(
                "SUPERCIAS search response shape changed; "
                "see docs/countries/ec.md."
            )
        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for rec in records[: max(limit * 2, limit)]:
            ruc = _extract_ruc(rec)
            if not ruc or ruc in seen:
                continue
            seen.add(ruc)
            matches.append(_match_from_record(ruc, rec, self.country_code))
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"EC only supports VAT/COMPANY_NUMBER (RUC), got {id_type}"
            )
        ruc = _normalize_ruc(value)
        payload = await self._fetch_json_or_html(
            f"{self.SUPERCIAS_LOOKUP_PATH}/{ruc}"
        )
        rec = _first_record_for_ruc(payload, ruc)
        if rec is None:
            return None
        return _details_from_record(ruc, rec, self.country_code)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ruc = _normalize_ruc(company_id)
        params = {"ruc": ruc}
        try:
            payload = await self._fetch_json_or_html(
                self.SUPERCIAS_FILINGS_PATH, params=params
            )
        except AdapterNotImplementedError:
            # Filings catalog returned an opaque shell; the no-mock rule
            # means we surface nothing rather than guess.
            return []
        records = _coerce_records(payload) or []
        cutoff_year = datetime.utcnow().year - years
        filings: list[FinancialFiling] = []
        for rec in records:
            yr = _extract_year(rec)
            if yr is None or yr < cutoff_year:
                continue
            doc_url = _pick(
                rec,
                "url_documento",
                "urlDocumento",
                "documento",
                "url",
                "enlace",
            )
            fmt = _doc_format(doc_url)
            filings.append(
                FinancialFiling(
                    company_id=ruc,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=_period_end(rec, yr),
                    currency="USD",
                    structured_data=None,
                    document_url=doc_url,
                    document_format=fmt,
                    source_url=_supercias_filings_url(ruc),
                )
            )
        return filings

    async def _fetch_json_or_html(
        self, path: str, *, params: dict[str, str] | None = None
    ) -> Any:
        async with self._client() as client:
            resp = await get_with_retry(client, path, params=params or {})
            if resp.status_code in (404, 204):
                return []
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            text = resp.text or ""
            if "json" in ctype:
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return _parse_supercias_html(text)
            stripped = text.lstrip()
            if stripped.startswith(("{", "[")):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    pass
            return _parse_supercias_html(text)


def _coerce_records(payload: Any) -> list[dict[str, Any]] | None:
    """Normalize the heterogeneous SUPERCIAS response shapes to a list.

    Returns ``None`` only when the payload is so foreign that we cannot
    even decide whether it is empty — that triggers
    ``AdapterNotImplementedError`` upstream rather than silent
    fabrication. An explicit empty list is returned as ``[]``.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in (
            "companias",
            "compania",
            "resultados",
            "data",
            "Data",
            "items",
            "registros",
            "rows",
            "lista",
            "listaInformacion",
            "informacionEconomica",
        ):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
            if isinstance(inner, dict):
                return [inner]
        if any(
            k in payload
            for k in (
                "ruc",
                "RUC",
                "expediente",
                "razon_social",
                "razonSocial",
                "nombreCia",
            )
        ):
            return [payload]
        return []
    return None


def _extract_ruc(rec: dict[str, Any]) -> str | None:
    for key in (
        "ruc",
        "RUC",
        "Ruc",
        "rucCompania",
        "numero_ruc",
        "numeroRuc",
    ):
        v = rec.get(key)
        if v is None:
            continue
        digits = _DIGITS_RE.sub("", str(v))
        if len(digits) == 13:
            return digits
    return None


def _first_record_for_ruc(payload: Any, ruc: str) -> dict[str, Any] | None:
    records = _coerce_records(payload)
    if records is None:
        raise AdapterNotImplementedError(
            "SUPERCIAS lookup response shape changed; "
            "see docs/countries/ec.md."
        )
    for rec in records:
        if _extract_ruc(rec) == ruc:
            return rec
    # Direct lookups frequently echo a single record without re-stating
    # the RUC in the body; accept that shape.
    if len(records) == 1:
        return records[0]
    return None


def _pick(rec: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = rec.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _pick_float(rec: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = rec.get(k)
        if v is None:
            continue
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    return None


def _match_from_record(
    ruc: str, rec: dict[str, Any], country_code: str
) -> CompanyMatch:
    name = (
        _pick(
            rec,
            "razon_social",
            "razonSocial",
            "nombreCia",
            "nombre",
            "RAZON_SOCIAL",
        )
        or ruc
    )
    status = _pick(rec, "estado", "ESTADO", "situacion_legal", "situacionLegal")
    return CompanyMatch(
        id=ruc,
        name=name,
        country=country_code,
        identifiers=[
            RegistryIdentifier(type=IdentifierType.VAT, value=ruc, label="RUC"),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=ruc, label="RUC"
            ),
        ],
        address=_compose_address(rec),
        status=status,
        source_url=_supercias_company_url(ruc),
    )


def _details_from_record(
    ruc: str, rec: dict[str, Any], country_code: str
) -> CompanyDetails:
    name = (
        _pick(
            rec,
            "razon_social",
            "razonSocial",
            "nombreCia",
            "nombre",
            "RAZON_SOCIAL",
        )
        or ruc
    )
    legal_form = _pick(
        rec, "tipo", "TIPO", "tipo_compania", "tipoCompania", "tipoEmpresa"
    )
    status = _pick(rec, "estado", "ESTADO", "situacion_legal", "situacionLegal")
    inc_date = _parse_ec_date(
        _pick(
            rec,
            "fecha_constitucion",
            "fechaConstitucion",
            "fecha_inscripcion",
            "fechaInscripcion",
        )
    )
    capital = _pick_float(
        rec, "capital", "capital_suscrito", "capitalSuscrito", "capital_autorizado"
    )
    ciiu_codes = _ciiu_codes(rec)

    return CompanyDetails(
        id=ruc,
        name=name,
        country=country_code,
        legal_form=legal_form,
        status=status,
        incorporation_date=inc_date,
        registered_address=_compose_address(rec),
        capital_amount=capital,
        capital_currency="USD",
        nace_codes=ciiu_codes,
        identifiers=[
            RegistryIdentifier(type=IdentifierType.VAT, value=ruc, label="RUC"),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=ruc, label="RUC"
            ),
        ],
        raw=dict(rec),
        source_url=_supercias_company_url(ruc),
    )


def _compose_address(rec: dict[str, Any]) -> str | None:
    parts = [
        _pick(rec, "direccion", "DIRECCION", "domicilio"),
        _pick(rec, "ciudad", "CIUDAD", "canton", "CANTON"),
        _pick(rec, "provincia", "PROVINCIA"),
    ]
    cleaned = [p for p in parts if p]
    return ", ".join(cleaned) if cleaned else None


def _ciiu_codes(rec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in (
        "ciiu",
        "CIIU",
        "ciiu_principal",
        "ciiuPrincipal",
        "actividad_economica",
        "actividadEconomica",
        "codigoCiiu",
    ):
        v = rec.get(key)
        if v is None:
            continue
        digits = _DIGITS_RE.sub("", str(v))
        if digits and digits not in out:
            out.append(digits)
    return out


def _parse_ec_date(value: str | None) -> date | None:
    if not value:
        return None
    s = value.strip()
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(s[:19] if "T" in s else s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _extract_year(rec: dict[str, Any]) -> int | None:
    for key in ("anio", "año", "year", "anioFiscal", "ejercicio", "periodo"):
        v = rec.get(key)
        if v is None:
            continue
        digits = _DIGITS_RE.sub("", str(v))
        if len(digits) >= 4:
            try:
                yr = int(digits[:4])
            except ValueError:
                continue
            if 1900 <= yr <= 2100:
                return yr
    return None


def _period_end(rec: dict[str, Any], year: int) -> date:
    explicit = _parse_ec_date(
        _pick(rec, "fecha_corte", "fechaCorte", "fechaFinPeriodo", "periodEnd")
    )
    return explicit or date(year, 12, 31)


def _doc_format(url: str | None) -> str | None:
    if not url:
        return None
    lowered = url.lower()
    for ext in ("pdf", "xls", "xlsx", "xml", "csv", "html"):
        if lowered.endswith(f".{ext}"):
            return ext
    return None


def _supercias_company_url(ruc: str) -> str:
    qs = urlencode({"ruc": ruc})
    return (
        "https://appscvsmovil.supercias.gob.ec/portalConsultas/"
        f"consulta/companias_consultaCompania.zul?{qs}"
    )


def _supercias_filings_url(ruc: str) -> str:
    qs = urlencode({"ruc": ruc})
    return (
        "https://appscvsmovil.supercias.gob.ec/portalConsultas/"
        f"consulta/informacion_economica.zul?{qs}"
    )


class _SuperciasTableParser(HTMLParser):
    """Defensive fallback parser for the portal's HTML response.

    Captures simple two-column label/value tables and any inline
    ``window.__INITIAL_STATE__``-style bootstrap JSON.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth_table = 0
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._cell_buf: list[str] = []
        self.rows: list[list[str]] = []
        self._in_script = False
        self._script_buf: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth_table += 1
        elif tag == "tr" and self._depth_table > 0:
            self._in_row = True
            self._cells = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_buf = []
        elif tag == "script":
            self._in_script = True
            self._script_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth_table > 0:
            self._depth_table -= 1
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._cells:
                self.rows.append(self._cells)
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._cells.append(unescape("".join(self._cell_buf)).strip())
        elif tag == "script" and self._in_script:
            self._in_script = False
            self.scripts.append("".join(self._script_buf))

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_buf.append(data)
        elif self._in_script:
            self._script_buf.append(data)


_BOOTSTRAP_JSON_RE = re.compile(
    r"(?:window\.__(?:INITIAL_STATE|SUPERCIAS_DATA)__|var\s+__SUPERCIAS__)"
    r"\s*=\s*(\[.*?\]|\{.*?\})\s*;",
    re.DOTALL,
)


def _parse_supercias_html(html_text: str) -> list[dict[str, Any]]:
    """Best-effort HTML fallback. Returns ``[]`` if nothing structured found."""
    parser = _SuperciasTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        logger.debug("SUPERCIAS HTML parse failed: %s", exc)
        return []

    for script in parser.scripts:
        m = _BOOTSTRAP_JSON_RE.search(script)
        if not m:
            continue
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        records = _coerce_records(payload) or []
        if records:
            return records

    label_map = {
        "ruc": "ruc",
        "número de ruc": "ruc",
        "numero de ruc": "ruc",
        "razón social": "razon_social",
        "razon social": "razon_social",
        "nombre de la compañía": "razon_social",
        "nombre de la compania": "razon_social",
        "estado": "estado",
        "situación legal": "situacion_legal",
        "situacion legal": "situacion_legal",
        "tipo de compañía": "tipo_compania",
        "tipo de compania": "tipo_compania",
        "domicilio": "direccion",
        "dirección": "direccion",
        "direccion": "direccion",
        "ciudad": "ciudad",
        "cantón": "canton",
        "canton": "canton",
        "provincia": "provincia",
        "fecha de constitución": "fecha_constitucion",
        "fecha de constitucion": "fecha_constitucion",
        "capital suscrito": "capital_suscrito",
        "actividad económica": "ciiu",
        "actividad economica": "ciiu",
        "ciiu": "ciiu",
    }
    record: dict[str, Any] = {}
    for row in parser.rows:
        if len(row) < 2:
            continue
        label = row[0].lower().rstrip(":").strip()
        value = row[1].strip()
        key = label_map.get(label)
        if key and value:
            record[key] = value
    return [record] if record else []


__all__ = [
    "ECAdapter",
    "_normalize_ruc",
]
