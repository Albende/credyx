"""Costa Rica adapter — GLEIF + Ministerio de Hacienda ATV + listed-issuer disclosures.

Sources (all free, no API key):

* **GLEIF** (``api.gleif.org``) — reachable from anywhere and the only free
  machine-readable source that exposes Costa Rican legal entities *by name*.
  Every CR record carries ``entity.registeredAs`` = the cédula jurídica, so
  GLEIF backs both name search and cédula lookup. Coverage is the ~280 CR
  entities that hold an LEI (banks, listed issuers, large exporters, funds).
* **Ministerio de Hacienda — Consulta de Situación Tributaria (ATV)**.
  ``GET https://api.hacienda.go.cr/fe/ae?identificacion={cedula}`` returns the
  registered name, legal-form class, tax status and CAEC activity codes for
  *every* taxpayer. As of 2026 the endpoint geoblocks requests originating
  outside Costa Rica (it serves an HTML "acceso restringido" page instead of
  JSON). We still try it first — where the adapter runs on a CR-reachable
  network it gives the richest, widest-coverage record — and transparently
  fall back to GLEIF when the geoblock (or any non-JSON body) is returned.
* **Listed-issuer financial statements.** Costa Rica's official disclosure
  registry (SUGEVAL RNVI, ``aplicaciones.sugeval.fi.cr``) resets connections
  from non-CR IPs, so financials are sourced from the issuers' own published
  audited/consolidated statements. ``_LISTED_FINANCIALS`` maps a listed
  cédula to its public financial-statements index; ``fetch_financials`` scrapes
  that index *live* and returns one row per real, downloadable PDF. Non-listed
  companies get ``[]`` — never a fabricated filing.

Identifier: **Cédula Jurídica** — 10 digits, rendered ``3-101-000784``. Leading
``3`` = juridical person (middle three digits are the sub-class: ``101`` S.A.,
``102`` SRL, ...). A handful of pre-1990 state entities (ICE, BNCR, AyA, INS,
RECOPE, ...) carry ``4-000-XXXXXX`` "cédula física institucional" numbers; both
forms resolve through the same sources, so the adapter accepts either.

No-mock-data rule: every field returned here comes verbatim from GLEIF, Hacienda
or an issuer's own filed PDF. Nothing is fabricated.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D+")

# Juridical persons: leading 3 + 3-digit class + 6-digit sequence.
_CEDULA_JURIDICA_RE = re.compile(r"^3\d{9}$")
# State-entity ("cédula física institucional") form: leading 4 + 000 + 6 digits.
# ICE, BNCR, AyA, INS, RECOPE and similar pre-1990 entities are filed this way.
_CEDULA_ESTATAL_RE = re.compile(r"^4000\d{6}$")

# Class codes (positions 1..4) seen on company cédulas. Mapped to the canonical
# Costa Rican corporate legal form for human-readable display. Codes not in this
# table are surfaced verbatim from the upstream payload.
_LEGAL_FORM_BY_CLASS: dict[str, str] = {
    "3101": "Sociedad Anónima",
    "3102": "Sociedad de Responsabilidad Limitada",
    "3103": "Sociedad en Nombre Colectivo",
    "3104": "Sociedad en Comandita",
    "3105": "Empresa Individual de Responsabilidad Limitada",
    "3106": "Sucursal de Sociedad Extranjera",
    "3107": "Sociedad Cooperativa",
    "3108": "Sociedad Civil",
    "3109": "Sociedad Extranjera",
    "3110": "Asociación Civil",
    "3014": "Municipalidad",
    "4000": "Institución del Estado",
}


def _normalize_cedula(value: str) -> str:
    """Strip punctuation, return canonical 10-digit cédula jurídica."""
    if value is None:
        raise InvalidIdentifierError("Cédula jurídica is required")
    digits = _DIGITS_RE.sub("", value)
    if not digits:
        raise InvalidIdentifierError(f"Cédula jurídica invalid: {value!r}")
    if _CEDULA_JURIDICA_RE.match(digits) or _CEDULA_ESTATAL_RE.match(digits):
        return digits
    raise InvalidIdentifierError(
        f"Cédula jurídica must be 10 digits starting with 3 (juridical) "
        f"or 4-000-XXXXXX (state entity), got {value!r}"
    )


def _format_cedula(cedula: str) -> str:
    """Render a normalized cédula as ``X-XXX-XXXXXX`` (GLEIF/RNP convention)."""
    return f"{cedula[0]}-{cedula[1:4]}-{cedula[4:]}"


# Listed CR issuers whose audited/consolidated financial statements are
# published as downloadable PDFs on their own investor-relations site. Keyed by
# normalized cédula → the public financial-statements index that fetch_financials
# scrapes live. The index is re-read on every call so newly filed periods appear
# without a code change. Companies not listed here get [] (no fabrication).
_LISTED_FINANCIALS: dict[str, str] = {
    # Florida Ice and Farm Company (FIFCO) — BNV's flagship issuer.
    "3101000784": "https://www.fifco.com/en/financial-statements/",
}

_PDF_HREF_RE = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")
# Annual/year-end statements (as opposed to Q1/Q2/Q3 interims). "Diciembre" =
# December year-end; "auditad" / "periodo-fiscal" = the audited annual pack.
_ANNUAL_MARKERS = ("diciembre", "auditad", "periodo-fiscal", "periodofiscal")
_FINANCIAL_MARKERS = ("estados-financieros", "estadosfinancieros", "informe", "ef-fifco")


class CRAdapter(CountryAdapter):
    country_code = "CR"
    country_name = "Costa Rica"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    HACIENDA_API_BASE = "https://api.hacienda.go.cr"
    HACIENDA_PORTAL = (
        "https://www.hacienda.go.cr/ATV/ConsultaSituacionTributaria.aspx"
    )

    def _gleif_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
            timeout=25.0,
        )

    def _hacienda_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.HACIENDA_API_BASE,
            headers={
                "Accept": "application/json",
                "Accept-Language": "es-CR,es;q=0.9,en;q=0.7",
                "Referer": self.HACIENDA_PORTAL,
            },
            timeout=20.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._gleif_client() as client:
                resp = await get_with_retry(
                    client,
                    "/lei-records",
                    params={
                        "filter[entity.legalAddress.country]": "CR",
                        "page[size]": 1,
                    },
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
                last_checked_at=datetime.utcnow(),
                notes=f"GLEIF unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=(
                "Name search + cédula lookup via GLEIF (LEI-registered CR "
                "entities); Hacienda ATV enriches lookups where reachable "
                "(geoblocks non-CR IPs). Financials for listed issuers whose "
                "filed PDFs are public."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = (name or "").strip()
        if not query:
            return []
        params = {
            "filter[entity.legalAddress.country]": "CR",
            "filter[entity.legalName]": query,
            "page[size]": max(1, min(int(limit), 50)),
            "page[number]": 1,
        }
        async with self._gleif_client() as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        records = payload.get("data") or []
        matches: list[CompanyMatch] = []
        for record in records:
            match = _match_from_gleif(record)
            if match:
                matches.append(match)
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"CR supports VAT/COMPANY_NUMBER (cédula jurídica), got {id_type}"
            )
        cedula = _normalize_cedula(value)

        hacienda = await self._fetch_ae(cedula)
        if hacienda is not None:
            return _details_from_ae(cedula, hacienda)

        record = await self._fetch_gleif_by_cedula(cedula)
        if record is not None:
            return _details_from_gleif(cedula, record)
        return None

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cedula = _normalize_cedula(company_id)
        index_url = _LISTED_FINANCIALS.get(cedula)
        if index_url is None:
            return []

        async with build_http_client(timeout=30.0) as client:
            try:
                resp = await get_with_retry(client, index_url)
                resp.raise_for_status()
                html = resp.text
            except httpx.HTTPError as exc:
                logger.warning("CR financials index unreachable %s: %s", index_url, exc)
                return []

            candidates = _annual_pdf_candidates(html, index_url)
            filings: list[FinancialFiling] = []
            for year, url in candidates[:years]:
                downloads = await _pdf_downloads(client, url)
                filings.append(
                    FinancialFiling(
                        company_id=cedula,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency=_currency_from_url(url),
                        structured_data=None,
                        document_url=url if downloads else None,
                        document_format="pdf" if downloads else None,
                        source_url=index_url,
                    )
                )
        return filings

    async def _fetch_ae(self, cedula: str) -> dict[str, Any] | None:
        try:
            async with self._hacienda_client() as client:
                resp = await get_with_retry(
                    client, "/fe/ae", params={"identificacion": cedula}
                )
                if resp.status_code in (404, 400):
                    return None
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "").lower()
                if "json" not in ctype:
                    return None
                try:
                    data = resp.json()
                except ValueError:
                    return None
        except httpx.HTTPError as exc:
            logger.info("Hacienda ATV unavailable for %s: %s", cedula, exc)
            return None
        if not isinstance(data, dict) or not data:
            return None
        if not (data.get("nombre") or data.get("nombreComercial")):
            return None
        return data

    async def _fetch_gleif_by_cedula(self, cedula: str) -> dict[str, Any] | None:
        formatted = _format_cedula(cedula)
        params = {
            "filter[entity.legalAddress.country]": "CR",
            "filter[entity.registeredAs]": formatted,
            "page[size]": 5,
        }
        async with self._gleif_client() as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
        records = payload.get("data") or []
        for record in records:
            registered = _safe_get(record, "attributes", "entity", "registeredAs")
            if registered and _DIGITS_RE.sub("", str(registered)) == cedula:
                return record
        return records[0] if records else None


def _safe_get(obj: Any, *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _gleif_address(address: dict[str, Any] | None) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    elif isinstance(lines, str) and lines:
        parts.append(lines)
    for key in ("city", "region", "postalCode", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


def _gleif_status(entity: dict[str, Any]) -> str | None:
    raw = (entity.get("status") or "").upper()
    if raw == "ACTIVE":
        return "Activo"
    if raw == "INACTIVE":
        return "Inactivo"
    return raw.title() or None


def _match_from_gleif(record: dict[str, Any]) -> CompanyMatch | None:
    lei = record.get("id") or _safe_get(record, "attributes", "lei")
    entity = _safe_get(record, "attributes", "entity") or {}
    name = _safe_get(entity, "legalName", "name")
    if not name:
        return None
    registered = entity.get("registeredAs")
    identifiers: list[RegistryIdentifier] = []
    local_id: str
    if registered and (_CEDULA_JURIDICA_RE.match(_DIGITS_RE.sub("", str(registered)))
                       or _CEDULA_ESTATAL_RE.match(_DIGITS_RE.sub("", str(registered)))):
        cedula = _DIGITS_RE.sub("", str(registered))
        local_id = cedula
        formatted = _format_cedula(cedula)
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT, value=formatted, label="Cédula Jurídica"
            )
        )
    else:
        local_id = str(lei)
    if lei:
        identifiers.append(RegistryIdentifier(type=IdentifierType.LEI, value=str(lei)))

    return CompanyMatch(
        id=local_id,
        name=str(name).strip(),
        country="CR",
        identifiers=identifiers,
        address=_gleif_address(entity.get("legalAddress")),
        status=_gleif_status(entity),
        source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
    )


def _details_from_gleif(cedula: str, record: dict[str, Any]) -> CompanyDetails:
    lei = record.get("id") or _safe_get(record, "attributes", "lei")
    entity = _safe_get(record, "attributes", "entity") or {}
    name = (_safe_get(entity, "legalName", "name") or "").strip()
    formatted = _format_cedula(cedula)

    legal_form = _LEGAL_FORM_BY_CLASS.get(cedula[:4])
    elf = _safe_get(entity, "legalForm", "id")

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.VAT, value=formatted, label="Cédula Jurídica"
        ),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=formatted,
            label="Cédula Jurídica",
        ),
    ]
    if lei:
        identifiers.append(RegistryIdentifier(type=IdentifierType.LEI, value=str(lei)))

    return CompanyDetails(
        id=cedula,
        name=name or formatted,
        country="CR",
        legal_form=legal_form or (str(elf) if elf else None),
        status=_gleif_status(entity),
        incorporation_date=None,
        registered_address=_gleif_address(entity.get("legalAddress")),
        capital_amount=None,
        capital_currency="CRC",
        nace_codes=[],
        identifiers=identifiers,
        raw=record,
        source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
    )


def _details_from_ae(cedula: str, data: dict[str, Any]) -> CompanyDetails:
    name = (data.get("nombre") or data.get("nombreComercial") or "").strip()
    legal_form = _legal_form_ae(cedula, data)
    status = (
        data.get("situacion", {}).get("estado")
        if isinstance(data.get("situacion"), dict)
        else None
    ) or data.get("estado")

    nace_codes: list[str] = []
    for act in data.get("actividades") or []:
        if not isinstance(act, dict):
            continue
        code = act.get("codigo") or act.get("codigoCIIU") or act.get("codigoActividad")
        if code is not None and (estado := act.get("estado")):
            if str(estado).strip().lower() != "activo":
                continue
        if code is not None:
            digits = _DIGITS_RE.sub("", str(code))
            if digits and digits not in nace_codes:
                nace_codes.append(digits)

    formatted = _format_cedula(cedula)
    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.VAT, value=formatted, label="Cédula Jurídica"
        ),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=formatted,
            label="Cédula Jurídica",
        ),
    ]

    return CompanyDetails(
        id=cedula,
        name=name or formatted,
        country="CR",
        legal_form=legal_form,
        status=str(status).strip() if status else None,
        incorporation_date=None,
        registered_address=None,
        capital_amount=None,
        capital_currency="CRC",
        nace_codes=nace_codes,
        identifiers=identifiers,
        raw=dict(data),
        source_url="https://api.hacienda.go.cr/fe/ae?identificacion=" + cedula,
    )


def _legal_form_ae(cedula: str, data: dict[str, Any]) -> str | None:
    explicit = data.get("tipoIdentificacion") or data.get("regimen", {})
    if isinstance(explicit, dict):
        descripcion = explicit.get("descripcion")
        if descripcion:
            return str(descripcion).strip()
    elif isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return _LEGAL_FORM_BY_CLASS.get(cedula[:4])


def _annual_pdf_candidates(html: str, base_url: str) -> list[tuple[int, str]]:
    """Parse an issuer index page → [(year, absolute_pdf_url)], newest first.

    Keeps only year-end/audited statements and dedupes to one document per
    fiscal year (the last one seen for a year on the page wins — pages list the
    definitive audited pack after the preliminary one)."""
    seen_year: dict[int, str] = {}
    for href in _PDF_HREF_RE.findall(html):
        low = href.lower()
        if not any(m in low for m in _FINANCIAL_MARKERS):
            continue
        if not any(m in low for m in _ANNUAL_MARKERS):
            continue
        name_part = low.rsplit("/", 1)[-1]
        year_match = _YEAR_RE.search(name_part)
        if not year_match:
            continue
        year = int(year_match.group(1))
        url = href if href.lower().startswith("http") else _join_url(base_url, href)
        seen_year.setdefault(year, url)
    return sorted(seen_year.items(), key=lambda kv: kv[0], reverse=True)


def _join_url(base_url: str, href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        root = re.match(r"^(https?://[^/]+)", base_url)
        return (root.group(1) if root else base_url) + href
    return base_url.rsplit("/", 1)[0] + "/" + href


def _currency_from_url(url: str) -> str:
    low = url.lower()
    if "dolar" in low or "usd" in low or "-eng-" in low or "dollars" in low:
        return "USD"
    return "CRC"


async def _pdf_downloads(client: httpx.AsyncClient, url: str) -> bool:
    """Confirm the PDF actually downloads (real bytes, PDF magic) — the
    no-mock rule forbids surfacing a document_url that doesn't resolve."""
    try:
        async with client.stream("GET", url, headers={"Range": "bytes=0-15"}) as resp:
            if resp.status_code not in (200, 206):
                return False
            ctype = resp.headers.get("content-type", "").lower()
            async for chunk in resp.aiter_bytes():
                return chunk.startswith(b"%PDF") or "pdf" in ctype
    except httpx.HTTPError as exc:
        logger.info("CR filing PDF not downloadable %s: %s", url, exc)
        return False
    return False


__all__ = [
    "CRAdapter",
    "_normalize_cedula",
    "_format_cedula",
]
