"""Ecuador adapter — GLEIF (reachable) for registry data; SUPERCIAS/SRI geo-walled.

Reachability (verified 2026-07): every Ecuadorian authoritative source sits
behind an Ecuador-only edge / anti-automation wall that rejects all non-EC
egress — SUPERCIAS' consulta portal (``appscvsgen.supercias.gob.ec``,
``appscvssoc.supercias.gob.ec``) answers every ``/consultaCompanias/*``
request with an "Unauthorized Request Blocked / Actividad no autorizada"
page (identical for curl, httpx, FlareSolverr, and a real headed Chrome),
SRI (``srienlinea.sri.gob.ec``) drops the TLS handshake, and
``datosabiertos.gob.ec`` / ``superbancos.gob.ec`` return 403. The legacy
mobile host ``appscvsmovil.supercias.gob.ec`` no longer routes at all. None
are reachable key-free from outside Ecuador, so live company data is sourced
from **GLEIF** — the free global LEI registry (JSON:API, no auth) — which
carries the Ecuadorian **RUC** in ``entity.registeredAs`` for most supervised
sociedades and lets us search by name and look up by RUC or LEI.

Identifier: **RUC** (Registro Único de Contribuyentes). 13 digits, layout
``PPCCCCCCCCDDD001`` (``PP`` province 01–24, digit 3 contributor class —
``9`` sociedad, ``6`` public institution, ``0–5`` natural person — then the
body id and the ``001`` head-office suffix). Exposed as ``VAT`` (primary —
the RUC is Ecuador's corporate tax identifier) and ``COMPANY_NUMBER``; the
entity's ``LEI`` is also accepted for lookup.

Financials: no free source of filed Ecuadorian financial statements is
reachable from outside Ecuador (SUPERCIAS "Información Económica" is behind
the same wall; the Quito/Guayaquil exchanges publish only static prospectus
PDFs with no per-company structured feed). Per the no-mock rule,
``fetch_financials`` raises ``AdapterNotImplementedError`` rather than
fabricate figures or point at a landing page.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_DIGITS_RE = re.compile(r"\D+")
_RUC_RE = re.compile(r"^\d{13}$")
_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")

# OMARSA — a stable, RUC-carrying active GLEIF entity for liveness probes.
_HEALTH_PROBE_RUC = "0990608504001"


def _normalize_ruc(value: str) -> str:
    """Strip prefixes/punctuation and validate length + digit-only.

    Accepts ``"1790010937001"``, ``"179.001.0937-001"``,
    ``"EC 1790010937001"``. Raises ``InvalidIdentifierError`` for anything
    else. We do not enforce a province-code (01–24) check: several legacy
    public-sector RUCs use prefixes outside the canonical province band.
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
    identifier_types = [
        IdentifierType.VAT,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.LEI,
    ]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    GLEIF_BASE = "https://api.gleif.org/api/v1"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
            timeout=25.0,
        )

    async def _gleif_records(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._client() as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    async def health_check(self) -> AdapterHealth:
        try:
            records = await self._gleif_records(
                {
                    "filter[entity.registeredAs]": _HEALTH_PROBE_RUC,
                    "filter[entity.legalAddress.country]": "EC",
                    "page[size]": 1,
                }
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
        ok = bool(records)
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": False},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry data via GLEIF LEI registry (RUC carried in "
                "registeredAs). SUPERCIAS/SRI are geo-blocked to Ecuador; "
                "filed financial statements are not reachable from non-EC "
                "egress — see docs/countries/ec.md."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not name or not name.strip():
            return []
        term = name.strip()
        size = max(1, min(int(limit), 50))
        records = await self._gleif_records(
            {
                "filter[entity.legalName]": term,
                "filter[entity.legalAddress.country]": "EC",
                "page[size]": size,
                "page[number]": 1,
            }
        )
        if not records:
            records = await self._gleif_records(
                {
                    "filter[fulltext]": term,
                    "filter[entity.legalAddress.country]": "EC",
                    "page[size]": size,
                    "page[number]": 1,
                }
            )
        matches: list[CompanyMatch] = []
        seen: set[str] = set()
        for rec in records:
            match = _match_from_record(rec, self.country_code)
            if match is None or match.id in seen:
                continue
            seen.add(match.id)
            matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.LEI:
            lei = (value or "").strip().upper()
            if not _LEI_RE.match(lei):
                raise InvalidIdentifierError(f"Malformed LEI: {value!r}")
            records = await self._gleif_records({"filter[lei]": lei})
            rec = records[0] if records else None
            return _details_from_record(rec, self.country_code) if rec else None

        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"EC supports VAT/COMPANY_NUMBER (RUC) or LEI, got {id_type}"
            )
        ruc = _normalize_ruc(value)
        records = await self._gleif_records(
            {
                "filter[entity.registeredAs]": ruc,
                "filter[entity.legalAddress.country]": "EC",
                "page[size]": 5,
            }
        )
        rec = _first_record_for_ruc(records, ruc)
        if rec is None:
            return None
        return _details_from_record(rec, self.country_code)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        _normalize_ruc(company_id)
        raise AdapterNotImplementedError(
            "No free source of filed Ecuadorian financial statements is "
            "reachable from outside Ecuador: SUPERCIAS 'Información Económica' "
            "and SRI are geo-blocked and the securities exchanges expose no "
            "per-company structured feed. See docs/countries/ec.md."
        )


def _entity(rec: dict[str, Any]) -> dict[str, Any]:
    attrs = rec.get("attributes")
    entity = attrs.get("entity") if isinstance(attrs, dict) else None
    return entity if isinstance(entity, dict) else {}


def _ruc_of(rec: dict[str, Any]) -> str | None:
    value = _entity(rec).get("registeredAs")
    if value is None:
        return None
    digits = _DIGITS_RE.sub("", str(value))
    return digits if len(digits) == 13 else None


def _lei_of(rec: dict[str, Any]) -> str | None:
    lei = rec.get("id") or _entity(rec).get("lei")
    return str(lei) if lei else None


def _name_of(rec: dict[str, Any]) -> str | None:
    legal_name = _entity(rec).get("legalName")
    if isinstance(legal_name, dict):
        name = legal_name.get("name")
        if name:
            return str(name)
    return None


def _status_of(rec: dict[str, Any]) -> str | None:
    raw = (_entity(rec).get("status") or "").upper()
    if not raw:
        return None
    return "active" if raw == "ACTIVE" else raw.lower()


def _identifiers(ruc: str | None, lei: str | None) -> list[RegistryIdentifier]:
    ids: list[RegistryIdentifier] = []
    if ruc:
        ids.append(RegistryIdentifier(type=IdentifierType.VAT, value=ruc, label="RUC"))
        ids.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=ruc, label="RUC"
            )
        )
    if lei:
        ids.append(RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI"))
    return ids


def _address_of(rec: dict[str, Any]) -> str | None:
    address = _entity(rec).get("legalAddress")
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(x) for x in lines if x)
    elif isinstance(lines, str) and lines:
        parts.append(lines)
    for key in ("city", "region", "postalCode", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


def _match_from_record(rec: dict[str, Any], country_code: str) -> CompanyMatch | None:
    name = _name_of(rec)
    if not name:
        return None
    ruc = _ruc_of(rec)
    lei = _lei_of(rec)
    stable_id = ruc or lei
    if not stable_id:
        return None
    return CompanyMatch(
        id=stable_id,
        name=name,
        country=country_code,
        identifiers=_identifiers(ruc, lei),
        address=_address_of(rec),
        status=_status_of(rec),
        source_url=_gleif_url(lei),
    )


def _first_record_for_ruc(
    records: list[dict[str, Any]], ruc: str
) -> dict[str, Any] | None:
    for rec in records:
        if _ruc_of(rec) == ruc:
            return rec
    return records[0] if len(records) == 1 else None


def _details_from_record(
    rec: dict[str, Any], country_code: str
) -> CompanyDetails | None:
    name = _name_of(rec)
    if not name:
        return None
    entity = _entity(rec)
    ruc = _ruc_of(rec)
    lei = _lei_of(rec)
    legal_form = entity.get("legalForm")
    legal_form_id = (
        legal_form.get("id") if isinstance(legal_form, dict) else None
    )
    return CompanyDetails(
        id=ruc or lei or "",
        name=name,
        country=country_code,
        legal_form=str(legal_form_id) if legal_form_id else None,
        status=_status_of(rec),
        incorporation_date=_parse_date(entity.get("creationDate")),
        registered_address=_address_of(rec),
        capital_currency="USD",
        identifiers=_identifiers(ruc, lei),
        raw=dict(rec),
        source_url=_gleif_url(lei),
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    candidate = text[:19] if "T" in text else text[:10]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _gleif_url(lei: str | None) -> str | None:
    return f"https://search.gleif.org/#/record/{lei}" if lei else None


__all__ = [
    "ECAdapter",
    "_normalize_ruc",
]
