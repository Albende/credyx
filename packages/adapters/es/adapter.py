"""Spain adapter — einforma registry preview + GLEIF + filings.xbrl.org ESEF.

Spain has no free official REST API for the Registro Mercantil, and VIES
confirms a CIF/NIF is a valid Spanish VAT registration but returns no name or
address for Spanish traders (both come back as ``---``). What is free and
usable, key-free:

- **einforma** publishes a free per-CIF preview page (registered name, legal
  form, registered address, activity) sourced from BORME / the Registro
  Mercantil. Used to resolve a CIF to its real registered company.
- **GLEIF** (Global LEI Foundation) exposes a free structured API for name
  search and for mapping a company name to its Legal Entity Identifier.
- **filings.xbrl.org** hosts every EU ESEF (iXBRL) annual report for free,
  keyed by LEI. This is the durable, downloadable source of filed accounts
  for Spanish listed issuers.

So ``search_by_name`` queries GLEIF; ``lookup_by_identifier`` validates the
CIF against VIES and enriches it from einforma; ``fetch_financials`` walks
CIF -> registered name (einforma) -> LEI (GLEIF) -> ESEF filings
(filings.xbrl.org), returning real downloadable annual reports. Private
companies that are not ESEF filers have no free filed accounts, so they
return an empty list rather than fabricated data.

CIF format: leading letter (organisation class) + 7 digits + check char
(letter or digit). The check character is computed from the 7-digit body.
"""
from __future__ import annotations

import re
import unicodedata
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

_CIF_RE = re.compile(r"^[A-HJ-NP-SUVW]\d{7}[0-9A-J]$")
_CIF_CHECK_LETTERS = "JABCDEFGHI"
_CIF_LETTER_REQUIRES_LETTER_CHECK = set("PQRSNW")
_CIF_LETTER_REQUIRES_DIGIT_CHECK = set("ABEH")

_VIES_HEALTH_PROBE = "A28015865"  # Telefónica — stable, always-valid CIF

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

_GLEIF_BASE = "https://api.gleif.org/api/v1/lei-records"
_GLEIF_HEADERS = {"Accept": "application/vnd.api+json"}
_FILINGS_BASE = "https://filings.xbrl.org"
_VIES_REST = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/ES/vat"
_EINFORMA_ENTITY = (
    "https://www.einforma.com/servlet/app/portal/ENTP/prod/ETIQUETA_EMPRESA/nif"
)

_LEGAL_FORM_TOKENS = {
    "SA", "SL", "SAU", "SLU", "SAL", "SLL", "SCA", "SC", "SRL",
    "SOCIEDAD", "ANONIMA", "LIMITADA", "RESPONSABILIDAD", "LABORAL",
    "UNIPERSONAL", "COOPERATIVA", "COMANDITARIA", "COLECTIVA", "CIVIL",
}


def _normalize_cif(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("ES"):
        cleaned = cleaned[2:]
    if not _CIF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Spanish CIF/NIF must be letter + 7 digits + check char: {value}"
        )
    if not _cif_checksum_ok(cleaned):
        raise InvalidIdentifierError(f"Spanish CIF/NIF checksum invalid: {value}")
    return cleaned


def _cif_checksum_ok(cif: str) -> bool:
    """Validate the Spanish CIF check character.

    Algorithm: doubling odd-positioned digits (1-indexed from the body),
    summing tens+units of each product, adding even-positioned digits, taking
    the last digit of the total, then 10 - that digit mod 10. Map to a digit
    or to a letter from `_CIF_CHECK_LETTERS` depending on the org-class
    letter.
    """
    body = cif[1:8]
    given = cif[8]
    odd_sum = 0
    even_sum = 0
    for i, ch in enumerate(body, start=1):
        n = int(ch)
        if i % 2 == 1:
            doubled = n * 2
            odd_sum += (doubled // 10) + (doubled % 10)
        else:
            even_sum += n
    total = odd_sum + even_sum
    control_digit = (10 - (total % 10)) % 10
    control_letter = _CIF_CHECK_LETTERS[control_digit]
    org_letter = cif[0]
    if org_letter in _CIF_LETTER_REQUIRES_LETTER_CHECK:
        return given == control_letter
    if org_letter in _CIF_LETTER_REQUIRES_DIGIT_CHECK:
        return given.isdigit() and int(given) == control_digit
    return given == str(control_digit) or given == control_letter


def _ascii_fold(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )


_LEGAL_FORM_CANON = [
    ("SOCIEDAD ANONIMA LABORAL", "SAL"),
    ("SOCIEDAD DE RESPONSABILIDAD LIMITADA", "SL"),
    ("SOCIEDAD LIMITADA LABORAL", "SLL"),
    ("SOCIEDAD LIMITADA", "SL"),
    ("SOCIEDAD ANONIMA", "SA"),
    ("SOCIEDAD COOPERATIVA", "SCOOP"),
]


def _norm_name(value: str) -> str:
    folded = _ascii_fold(value).upper()
    for phrase, short in _LEGAL_FORM_CANON:
        folded = folded.replace(phrase, short)
    return re.sub(r"[^A-Z0-9]", "", folded)


def _name_core_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[A-Z0-9]+", _ascii_fold(value).upper())
    core = [t for t in tokens if t not in _LEGAL_FORM_TOKENS]
    return core or tokens


class ESAdapter(CountryAdapter):
    country_code = "ES"
    country_name = "Spain"
    identifier_types = [IdentifierType.CIF, IdentifierType.NIF, IdentifierType.VAT]
    primary_identifier = IdentifierType.CIF
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        try:
            details = await self.lookup_by_identifier(
                IdentifierType.CIF, _VIES_HEALTH_PROBE
            )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"Lookup probe failed: {str(exc)[:160]}",
            )
        if details is None or not details.name or details.name == _VIES_HEALTH_PROBE:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Telefónica probe reachable but returned no registered name.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search via GLEIF; lookup via einforma + VIES; financials via "
                "ESEF filings (filings.xbrl.org) for listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        params = {
            "filter[entity.legalName]": name,
            "filter[entity.legalAddress.country]": "ES",
            "page[size]": str(max(1, min(limit, 50))),
        }
        async with build_http_client(timeout=30.0, headers=_GLEIF_HEADERS) as client:
            resp = await get_with_retry(client, _GLEIF_BASE, params=params)
            if resp.status_code != 200:
                return []
            payload = resp.json()
        matches: list[CompanyMatch] = []
        for record in payload.get("data", []):
            attrs = record.get("attributes", {})
            entity = attrs.get("entity", {})
            lei = attrs.get("lei") or record.get("id")
            legal_name = (entity.get("legalName") or {}).get("name")
            if not lei or not legal_name:
                continue
            matches.append(
                CompanyMatch(
                    id=lei,
                    name=legal_name,
                    country="ES",
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
                    ],
                    address=_gleif_address(entity.get("legalAddress")),
                    status=_gleif_status((attrs.get("registration") or {}).get("status")),
                    source_url=f"{_GLEIF_BASE}/{lei}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (
            IdentifierType.CIF,
            IdentifierType.NIF,
            IdentifierType.VAT,
        ):
            raise InvalidIdentifierError(f"ES supports CIF/NIF/VAT, got {id_type}")
        cif = _normalize_cif(value)
        vat_valid = await self._vies_valid(cif)
        registry = await self._einforma_lookup(cif)
        if registry is None and not vat_valid:
            return None

        name = (registry or {}).get("name") or cif
        identifiers = [
            RegistryIdentifier(type=IdentifierType.CIF, value=cif, label="CIF"),
            RegistryIdentifier(type=IdentifierType.VAT, value=f"ES{cif}", label="VAT"),
        ]
        return CompanyDetails(
            id=cif,
            name=name,
            country="ES",
            legal_form=(registry or {}).get("legal_form")
            or _legal_form_from_cif_letter(cif[0]),
            status="active" if vat_valid else (registry or {}).get("status"),
            registered_address=(registry or {}).get("address"),
            capital_currency="EUR",
            nace_codes=(registry or {}).get("nace_codes", []),
            identifiers=identifiers,
            raw={
                "vies": {"valid": vat_valid},
                "einforma": registry,
            },
            source_url=f"{_EINFORMA_ENTITY}/{cif}" if registry else None,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cif = _normalize_cif(company_id)
        registry = await self._einforma_lookup(cif)
        if not registry or not registry.get("name"):
            return []
        lei = await self._resolve_lei(registry["name"])
        if not lei:
            return []
        filings = await self._esef_filings(lei)
        return self._select_filings(cif, filings, years)

    async def _vies_valid(self, cif: str) -> bool:
        try:
            async with build_http_client(
                timeout=20.0, headers={"Accept": "application/json"}
            ) as client:
                resp = await client.get(f"{_VIES_REST}/{cif}")
            if resp.status_code != 200:
                return False
            return bool(resp.json().get("isValid"))
        except (httpx.HTTPError, ValueError):
            return False

    async def _einforma_lookup(self, cif: str) -> dict[str, Any] | None:
        url = f"{_EINFORMA_ENTITY}/{cif}"
        try:
            async with build_http_client(
                timeout=25.0, headers={"User-Agent": _BROWSER_UA}
            ) as client:
                resp = await get_with_retry(client, url)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        return _parse_einforma(resp.text)

    async def _resolve_lei(self, registered_name: str) -> str | None:
        core = _name_core_tokens(registered_name)
        if not core:
            return None
        params = {
            "filter[entity.legalName]": " ".join(core),
            "filter[entity.legalAddress.country]": "ES",
            "page[size]": "15",
        }
        async with build_http_client(timeout=30.0, headers=_GLEIF_HEADERS) as client:
            resp = await get_with_retry(client, _GLEIF_BASE, params=params)
            if resp.status_code != 200:
                return None
            payload = resp.json()
        target = _norm_name(registered_name)
        best: tuple[int, int, int, str] | None = None
        for record in payload.get("data", []):
            attrs = record.get("attributes", {})
            lei = attrs.get("lei") or record.get("id")
            cand_name = ((attrs.get("entity") or {}).get("legalName") or {}).get("name")
            if not lei or not cand_name:
                continue
            cand = _norm_name(cand_name)
            if cand == target:
                score = 3
            elif cand.startswith(target) or target.startswith(cand):
                score = 2
            else:
                continue
            issued = 1 if (
                (attrs.get("registration") or {}).get("status") == "ISSUED"
            ) else 0
            key = (score, issued, -len(cand), lei)
            if best is None or key > best:
                best = key
        return best[3] if best else None

    async def _esef_filings(self, lei: str) -> list[dict[str, Any]]:
        flt = (
            '[{"name":"entity.identifier","op":"eq","val":"%s"}]' % lei
        )
        params = {"filter": flt, "page[size]": "100"}
        async with build_http_client(timeout=30.0, headers=_GLEIF_HEADERS) as client:
            resp = await get_with_retry(client, f"{_FILINGS_BASE}/api/filings", params=params)
            if resp.status_code != 200:
                return []
            payload = resp.json()
        return [item.get("attributes", {}) for item in payload.get("data", [])]

    def _select_filings(
        self, cif: str, filings: list[dict[str, Any]], years: int
    ) -> list[FinancialFiling]:
        by_period: dict[str, dict[str, Any]] = {}
        for attrs in filings:
            period_end = attrs.get("period_end")
            if not period_end:
                continue
            current = by_period.get(period_end)
            if current is None or (
                attrs.get("country") == "ES" and current.get("country") != "ES"
            ):
                by_period[period_end] = attrs
        selected = sorted(by_period.values(), key=lambda a: a["period_end"], reverse=True)
        result: list[FinancialFiling] = []
        for attrs in selected[: max(1, years)]:
            period = _parse_date(attrs["period_end"])
            document_path = attrs.get("package_url") or attrs.get("report_url")
            viewer_path = attrs.get("viewer_url") or attrs.get("report_url")
            result.append(
                FinancialFiling(
                    company_id=cif,
                    year=period.year if period else 0,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period,
                    currency="EUR",
                    structured_data=None,
                    document_url=(
                        f"{_FILINGS_BASE}{document_path}" if document_path else None
                    ),
                    document_format="xbrl" if attrs.get("package_url") else "xhtml",
                    source_url=f"{_FILINGS_BASE}{viewer_path}" if viewer_path else None,
                )
            )
        return result


def _gleif_address(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts = list(addr.get("addressLines") or [])
    for key in ("postalCode", "city", "country"):
        if addr.get(key):
            parts.append(addr[key])
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _gleif_status(status: str | None) -> str | None:
    if not status:
        return None
    return "active" if status == "ISSUED" else status.lower()


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _einforma_field(html_text: str, label: str) -> str | None:
    match = re.search(
        r"<strong>\s*" + re.escape(label) + r"[^<]*:?\s*</strong>\s*</td>\s*<td[^>]*>(.*?)</td>",
        html_text,
        re.S | re.I,
    )
    if not match:
        return None
    raw = match.group(1).split("<a")[0]
    text = re.sub(r"<[^>]+>", " ", raw)
    return _html_unescape(text).strip() or None


def _html_unescape(value: str) -> str:
    import html

    return re.sub(r"\s+", " ", html.unescape(value))


def _parse_einforma(html_text: str) -> dict[str, Any] | None:
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if not heading:
        return None
    name = _html_unescape(re.sub(r"<[^>]+>", " ", heading.group(1))).strip()
    if not name:
        return None
    address_parts = [
        _einforma_field(html_text, "Domicilio social actual"),
        _einforma_field(html_text, "Localidad"),
    ]
    address = ", ".join(p for p in address_parts if p) or None
    cnae = _einforma_field(html_text, "CNAE")
    nace_codes = re.findall(r"\b(\d{3,4})\b", cnae)[:1] if cnae else []
    return {
        "name": name,
        "legal_form": _einforma_field(html_text, "Forma Jur"),
        "address": address,
        "activity": cnae,
        "nace_codes": nace_codes,
    }


def _legal_form_from_cif_letter(letter: str) -> str | None:
    return {
        "A": "Sociedad Anónima",
        "B": "Sociedad de Responsabilidad Limitada",
        "C": "Sociedad Colectiva",
        "D": "Sociedad Comanditaria",
        "E": "Comunidad de Bienes",
        "F": "Sociedad Cooperativa",
        "G": "Asociación",
        "H": "Comunidad de Propietarios",
        "J": "Sociedad Civil",
        "P": "Corporación Local",
        "Q": "Organismo Público",
        "R": "Congregación Religiosa",
        "S": "Órgano de la Administración",
        "U": "Unión Temporal de Empresas",
        "V": "Otros tipos",
        "N": "Entidad Extranjera",
        "W": "Establecimiento Permanente de Entidad No Residente",
    }.get(letter.upper())
