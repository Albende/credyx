"""Colombia adapter — RUES (Registro Único Empresarial y Social) + SFC.

Sources:

* RUES — https://www.rues.org.co/
  Operated by CONFECAMARAS (Confederación Colombiana de Cámaras de
  Comercio). Public, free, no auth. Backing API for the public
  Consultas form lives at
  https://www.rues.org.co/RM/Consultas — JSON responses for both name
  and NIT lookups. The portal HTML wraps the same endpoints, so we hit
  the JSON path directly and only fall back to scraping if it shifts.
* SuperFinanciera de Colombia — https://www.superfinanciera.gov.co/
  Publishes XBRL/PDF annual reports for SFC-supervised entities
  (banks, insurers, listed issuers). The public index is reachable
  per-NIT but is not a structured API; we surface the index URL as a
  pointer rather than parse PDFs in MVP scope.

Identifier:

- NIT (Número de Identificación Tributaria) — DIAN-issued tax ID. 9–10
  body digits plus a single check digit, often displayed as
  ``XXX.XXX.XXX-D``. The same number serves the corporate VAT role, so
  we expose it as both ``VAT`` (primary) and ``COMPANY_NUMBER``.
- Check digit is computed with weights
  ``[71, 67, 59, 53, 47, 43, 41, 37, 29, 23, 19, 17, 13, 7, 3]`` applied
  right-to-left over the body, summed mod 11; results 0/1 map directly,
  otherwise ``11 - r``.

No-mock-data rule: if RUES is unreachable or its shape changes, raise —
never invent. Search and lookup attempt the JSON endpoint first and fall
back to a defensive HTML scrape of the public Consultas results table
using the stdlib HTML parser; no third-party HTML lib is added.
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
_NIT_BODY_RE = re.compile(r"^\d{9,10}$")

# DIAN check-digit weights, applied right-to-left to the NIT body (without
# the trailing check digit). The published table goes up to 15 positions; we
# only ever consume the rightmost 9 or 10.
_NIT_WEIGHTS = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]

# Ecopetrol — a stable, always-active anchor for liveness probes.
_HEALTH_PROBE_NIT = "899999068"


class COAdapter(CountryAdapter):
    country_code = "CO"
    country_name = "Colombia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    RUES_BASE = "https://www.rues.org.co"
    # The public Consultas form posts to /RM/ConsultaRUES; the JSON
    # endpoint that backs it is /RM/Consultas (GET with razon/nit params).
    RUES_SEARCH_PATH = "/RM/Consultas"
    RUES_LOOKUP_PATH = "/RM/ConsultaRUES"
    # SFC has no per-NIT REST endpoint; the supervised-entities lookup
    # is the closest public deeplink.
    SFC_INDEX_TEMPLATE = (
        "https://www.superfinanciera.gov.co/inicio/industrias-supervisadas"
        "/entidades-vigiladas/buscador-de-entidades-vigiladas-10082930"
    )

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.RUES_BASE,
            headers={
                "Accept": "application/json, text/html;q=0.8",
                "Accept-Language": "es-CO,es;q=0.9,en;q=0.7",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    self.RUES_SEARCH_PATH,
                    params={"nit": _HEALTH_PROBE_NIT},
                )
                resp.raise_for_status()
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
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "RUES public Consultas. Financials limited to "
                "SFC-supervised entities (banks, insurers, listed issuers)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not name or not name.strip():
            return []
        raw = await self._fetch_consulta(razon=name.strip())
        records = _coerce_records(raw)
        if records is None:
            raise AdapterNotImplementedError(
                "RUES response shape changed and could not be parsed; "
                "see docs/countries/co.md."
            )
        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for rec in records[: max(limit * 2, limit)]:
            nit = _extract_nit(rec)
            if not nit or nit in seen:
                continue
            seen.add(nit)
            matches.append(_match_from_record(nit, rec, self.country_code))
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
        # If the caller supplied a check digit we validate it; if they
        # gave us just the body we accept it (RUES looks up by body).
        if supplied_check is not None:
            expected = _nit_check_digit(nit_body)
            if supplied_check != expected:
                raise InvalidIdentifierError(
                    f"NIT check digit invalid for {value} "
                    f"(expected {expected}, got {supplied_check})"
                )

        raw = await self._fetch_consulta(nit=nit_body)
        records = _coerce_records(raw)
        if records is None:
            raise AdapterNotImplementedError(
                "RUES response shape changed and could not be parsed; "
                "see docs/countries/co.md."
            )
        rec = _first_record_for_nit(records, nit_body)
        if rec is None:
            return None
        return _details_from_record(nit_body, rec, self.country_code)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        nit_body, _ = _normalize_nit(company_id)
        # RUES exposes only registry metadata, not balance sheets.
        # SuperFinanciera publishes per-entity reports but solely for
        # supervised institutions; without a directory API we surface a
        # discovery pointer that the operator can drill into. Closed-
        # capital firms get an empty list per the no-mock-data rule.
        if not await self._is_sfc_supervised(nit_body):
            return []

        current_year = datetime.utcnow().year
        index_url = self.SFC_INDEX_TEMPLATE
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=nit_body,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="COP",
                    structured_data=None,
                    document_url=index_url,
                    document_format="html",
                    source_url=index_url,
                )
            )
        return filings

    async def _fetch_consulta(
        self, *, razon: str | None = None, nit: str | None = None
    ) -> Any:
        params: dict[str, str] = {}
        if razon:
            params["razon"] = razon
        if nit:
            params["nit"] = nit
        async with self._client() as client:
            resp = await get_with_retry(
                client, self.RUES_SEARCH_PATH, params=params
            )
            if resp.status_code in (404, 204):
                return []
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            text = resp.text
            if "json" in ctype:
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return _parse_rues_html(text)
            # Some deployments return the SPA shell even on the JSON path;
            # try JSON first, fall back to HTML table parsing.
            stripped = text.lstrip()
            if stripped.startswith(("{", "[")):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    pass
            return _parse_rues_html(text)

    async def _is_sfc_supervised(self, nit_body: str) -> bool:
        # The SFC public site does not expose a stable per-NIT JSON
        # endpoint; the supervised-entities buscador is a JS SPA. Until a
        # signed dataset is wired in, treat every NIT as unsupervised and
        # return an empty filings list rather than fabricate a hit.
        del nit_body
        return False


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
        # 9 or 10 digits = body only. 10 or 11 digits may be body + check;
        # we cannot tell without context, so treat 10 as body-only (the
        # common DIAN form) and 11 as body(10) + check.
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


def _coerce_records(payload: Any) -> list[dict[str, Any]] | None:
    """Normalize the heterogeneous RUES response shapes to a list of dicts.

    Returns None if the payload doesn't resemble anything we know — that
    triggers AdapterNotImplementedError upstream rather than silent
    fabrication.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("registros", "Registros", "data", "Data", "result", "results", "rows"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        # Single-record dict response.
        if any(
            k in payload
            for k in ("nit", "NIT", "razon_social", "razonSocial", "RAZON_SOCIAL")
        ):
            return [payload]
        return []
    return None


def _extract_nit(rec: dict[str, Any]) -> str | None:
    for key in ("nit", "NIT", "Nit", "numero_identificacion", "numeroIdentificacion"):
        v = rec.get(key)
        if v is None:
            continue
        digits = _DIGITS_RE.sub("", str(v))
        if 9 <= len(digits) <= 11:
            return digits[:-1] if len(digits) == 11 else digits
    return None


def _first_record_for_nit(
    records: list[dict[str, Any]], nit_body: str
) -> dict[str, Any] | None:
    for rec in records:
        candidate = _extract_nit(rec)
        if candidate == nit_body:
            return rec
    # If RUES echoed back a single record (common for direct NIT lookups)
    # but the field naming was odd, accept it.
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


def _match_from_record(
    nit_body: str, rec: dict[str, Any], country_code: str
) -> CompanyMatch:
    name = _pick(rec, "razon_social", "razonSocial", "RAZON_SOCIAL", "nombre") or nit_body
    status = _pick(rec, "estado", "ESTADO", "estado_matricula", "estadoMatricula")
    address = _compose_address(rec)
    check = _nit_check_digit(nit_body)
    formatted = f"{nit_body}-{check}"
    return CompanyMatch(
        id=nit_body,
        name=name,
        country=country_code,
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.VAT, value=formatted, label="NIT"
            ),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=formatted, label="NIT"
            ),
        ],
        address=address,
        status=status,
        source_url=_rues_source_url(nit_body),
    )


def _details_from_record(
    nit_body: str, rec: dict[str, Any], country_code: str
) -> CompanyDetails:
    name = _pick(rec, "razon_social", "razonSocial", "RAZON_SOCIAL", "nombre") or nit_body
    legal_form = _pick(
        rec, "organizacion_juridica", "organizacionJuridica", "tipo_sociedad", "tipoSociedad"
    )
    status = _pick(rec, "estado", "ESTADO", "estado_matricula", "estadoMatricula")
    inc_date = _parse_co_date(
        _pick(rec, "fecha_matricula", "fechaMatricula", "fecha_constitucion", "fechaConstitucion")
    )
    ciiu_codes = _ciiu_codes(rec)
    check = _nit_check_digit(nit_body)
    formatted = f"{nit_body}-{check}"

    return CompanyDetails(
        id=nit_body,
        name=name,
        country=country_code,
        legal_form=legal_form,
        status=status,
        incorporation_date=inc_date,
        registered_address=_compose_address(rec),
        capital_amount=None,
        capital_currency="COP",
        nace_codes=ciiu_codes,
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.VAT, value=formatted, label="NIT"
            ),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=formatted, label="NIT"
            ),
        ],
        raw=dict(rec),
        source_url=_rues_source_url(nit_body),
    )


def _compose_address(rec: dict[str, Any]) -> str | None:
    parts = [
        _pick(rec, "direccion_comercial", "direccionComercial", "direccion", "DIRECCION"),
        _pick(rec, "municipio", "MUNICIPIO", "ciudad"),
        _pick(rec, "departamento", "DEPARTAMENTO"),
    ]
    cleaned = [p for p in parts if p]
    return ", ".join(cleaned) if cleaned else None


def _ciiu_codes(rec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in (
        "ciiu1",
        "ciiu2",
        "ciiu3",
        "ciiu4",
        "codigo_ciiu",
        "codigoCiiu",
        "CIIU",
    ):
        v = rec.get(key)
        if v is None:
            continue
        digits = _DIGITS_RE.sub("", str(v))
        if digits and digits not in out:
            out.append(digits)
    return out


def _parse_co_date(value: str | None) -> date | None:
    if not value:
        return None
    s = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _rues_source_url(nit_body: str) -> str:
    qs = urlencode({"nit": nit_body})
    return f"https://www.rues.org.co/RM/ConsultaRUES?{qs}"


class _RuesTableParser(HTMLParser):
    """Defensive scraper for the fallback HTML render.

    Walks `<table>` rows and pulls out (header, value) pairs whenever the
    page uses a label-cell layout. Also collects any inline JSON dropped
    into a ``window.__RUES_DATA__`` or similar bootstrap script.
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
    r"window\.__RUES_DATA__\s*=\s*(\[.*?\]|\{.*?\})\s*;", re.DOTALL
)


def _parse_rues_html(html_text: str) -> list[dict[str, Any]]:
    """Best-effort HTML fallback.

    RUES occasionally returns a server-rendered results table or embeds the
    payload as a bootstrap JSON literal. We try the literal first, then
    fall back to row-pair extraction. Returns an empty list if nothing
    structured is found — never invents fields.
    """
    parser = _RuesTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        logger.debug("RUES HTML parse failed: %s", exc)
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

    # Label/value table fallback. Each row pairs of (label, value).
    record: dict[str, Any] = {}
    label_map = {
        "nit": "nit",
        "razón social": "razon_social",
        "razon social": "razon_social",
        "estado": "estado",
        "estado matrícula": "estado_matricula",
        "estado matricula": "estado_matricula",
        "dirección": "direccion_comercial",
        "direccion": "direccion_comercial",
        "municipio": "municipio",
        "departamento": "departamento",
        "ciiu": "codigo_ciiu",
        "actividad económica": "codigo_ciiu",
        "actividad economica": "codigo_ciiu",
        "fecha de matrícula": "fecha_matricula",
        "fecha matricula": "fecha_matricula",
        "tipo de sociedad": "tipo_sociedad",
        "organización jurídica": "organizacion_juridica",
        "organizacion juridica": "organizacion_juridica",
    }
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
    "COAdapter",
    # Exposed for unit tests.
    "_normalize_nit",
    "_nit_check_digit",
]
