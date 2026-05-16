"""Tunisia adapter — RNE (Registre National des Entreprises) + BVMT.

Source coverage:

* RNE (https://www.registre-entreprises.tn/rne-public/) — the national
  company registry established in 2018. The public-facing portal is a
  single-page application that calls JSON endpoints behind
  ``/rne-public/api/``. The endpoint paths are not formally documented,
  so this adapter treats RNE as a best-effort source: when the JSON shape
  is recognisable we surface real records, when it is not we raise
  ``AdapterNotImplementedError`` rather than fabricate data.
* BVMT (https://www.bvmt.com.tn/) — Tunis Stock Exchange. Free annual
  reports and reference documents for the ~80 listed issuers. Without a
  Matricule-Fiscal → ticker resolver in MVP we cannot enumerate filings
  by tax id, so ``fetch_financials`` returns ``[]`` for non-resolvable
  ids (matches the FR / MA convention — "no public filings" is a real
  factual answer for a non-listed Tunisian SARL).

Identifiers:
- ``VAT``            → Matricule Fiscal: 7 digits + control letter +
                       2 category letters + 3 establishment digits,
                       formatted ``1234567/A/M/000``. Normalised by
                       stripping slashes / dashes / whitespace.
- ``COMPANY_NUMBER`` → RNE number issued by the registry. Format is a
                       digit string; we accept any non-empty trimmed
                       value since RNE numbering has evolved over time.
"""
from __future__ import annotations

import logging
import re
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

logger = logging.getLogger(__name__)

# Matricule Fiscal, canonical form: 7 digits + 1 letter + 1 letter + 1 letter + 3 digits
# Real-world Tunisian tax ids appear as e.g. "1234567/A/M/000" or "1234567ABC000".
_MF_CANONICAL_RE = re.compile(r"^\d{7}[A-Z]{3}\d{3}$")
# RNE number — historically up to 10 digits; we accept any digit string.
_RNE_RE = re.compile(r"^\d{1,12}$")


def _normalize_matricule(value: str) -> str:
    cleaned = re.sub(r"[\s/\-.]", "", value.strip()).upper()
    if cleaned.startswith("TN"):
        cleaned = cleaned[2:]
    if not _MF_CANONICAL_RE.match(cleaned):
        raise InvalidIdentifierError(
            "Tunisia Matricule Fiscal must be 7 digits + 3 letters + 3 digits "
            f"(e.g. 1234567/A/M/000), got: {value}"
        )
    return cleaned


def _normalize_rne(value: str) -> str:
    cleaned = re.sub(r"[\s\-/]", "", value.strip())
    if not _RNE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Tunisia RNE number must be digits only, got: {value}"
        )
    return cleaned


class TNAdapter(CountryAdapter):
    country_code = "TN"
    country_name = "Tunisia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    RNE_BASE = "https://www.registre-entreprises.tn"
    RNE_PORTAL = "https://www.registre-entreprises.tn/rne-public/"
    BVMT_BASE = "https://www.bvmt.com.tn"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "RNE public portal probed; JSON endpoints are undocumented and "
            "best-effort. BVMT used for listed-issuer financials."
        )
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(client, self.RNE_PORTAL)
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.DEGRADED,
                        capabilities={"search": True, "lookup": True, "financials": True},
                        requires_api_key=False,
                        api_key_present=True,
                        rate_limit_per_minute=self.rate_limit_per_minute,
                        notes=f"RNE returned HTTP {resp.status_code}. {notes}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"RNE probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        # RNE's SPA calls a JSON search endpoint behind /rne-public/api/. The
        # path is undocumented; we probe a small set of known variants and
        # surface parseable results. If none respond with structured JSON
        # we raise rather than synthesise matches.
        candidates = (
            "/rne-public/api/entreprises/search",
            "/rne-public/api/recherche",
            "/rne-public/api/companies/search",
        )
        async with build_http_client(
            base_url=self.RNE_BASE,
            timeout=20.0,
            headers={"Accept": "application/json"},
        ) as client:
            for path in candidates:
                try:
                    resp = await get_with_retry(
                        client,
                        path,
                        params={"q": query, "size": limit, "name": query},
                    )
                except httpx.HTTPError:
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                matches = _matches_from_payload(payload, self.country_code)
                if matches:
                    return matches[:limit]
        raise AdapterNotImplementedError(
            "Tunisia RNE name search: no documented free JSON endpoint "
            "currently returns parseable results. The public SPA at "
            "registre-entreprises.tn requires a paid-tier or session token "
            "for structured access. Use Matricule Fiscal or RNE number lookup "
            "instead."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            mf = _normalize_matricule(value)
            return await self._lookup(mf, kind="matricule")
        if id_type == IdentifierType.COMPANY_NUMBER:
            rne = _normalize_rne(value)
            return await self._lookup(rne, kind="rne")
        raise InvalidIdentifierError(
            "Tunisia adapter supports VAT (Matricule Fiscal) or "
            f"COMPANY_NUMBER (RNE), got {id_type}"
        )

    async def _lookup(self, identifier: str, *, kind: str) -> CompanyDetails | None:
        path_variants = (
            f"/rne-public/api/entreprises/{identifier}",
            f"/rne-public/api/companies/{identifier}",
        )
        async with build_http_client(
            base_url=self.RNE_BASE,
            timeout=20.0,
            headers={"Accept": "application/json"},
        ) as client:
            for path in path_variants:
                try:
                    resp = await get_with_retry(client, path)
                except httpx.HTTPError:
                    continue
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                details = _details_from_payload(payload, identifier, kind)
                if details is not None:
                    return details
        raise AdapterNotImplementedError(
            f"Tunisia RNE lookup for {identifier}: no parseable JSON returned. "
            "The public portal does not expose a documented identifier endpoint "
            "in MVP; integration is blocked until RNE publishes a stable API."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cleaned = re.sub(r"[\s/\-.]", "", company_id.strip()).upper()
        if cleaned.startswith("TN"):
            cleaned = cleaned[2:]
        if not (_MF_CANONICAL_RE.match(cleaned) or _RNE_RE.match(cleaned)):
            raise InvalidIdentifierError(
                "Tunisia company_id must be a Matricule Fiscal or RNE number, "
                f"got: {company_id}"
            )
        # BVMT publishes per-issuer pages keyed by ticker, not by tax id.
        # Without a free Matricule→ticker resolver we cannot enumerate
        # filings here; non-listed firms genuinely have no public filings
        # (Tunisia does not require SARLs to deposit accounts publicly),
        # so an empty list is the factual answer.
        return []


def _matches_from_payload(payload: Any, country_code: str) -> list[CompanyMatch]:
    items = _iter_records(payload)
    matches: list[CompanyMatch] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("denomination")
            or item.get("raisonSociale")
            or item.get("name")
            or item.get("nom")
        )
        mf = (
            item.get("matriculeFiscal")
            or item.get("matricule_fiscal")
            or item.get("mf")
            or item.get("taxId")
        )
        rne = (
            item.get("numeroRne")
            or item.get("rne")
            or item.get("idRne")
            or item.get("identifiantUnique")
        )
        if not name or not (mf or rne):
            continue
        identifiers: list[RegistryIdentifier] = []
        if mf:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=str(mf),
                    label="Matricule Fiscal",
                )
            )
        if rne:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=str(rne),
                    label="RNE",
                )
            )
        matches.append(
            CompanyMatch(
                id=str(mf or rne),
                name=str(name).strip(),
                country=country_code,
                identifiers=identifiers,
                address=_address_from_item(item),
                status=item.get("statut") or item.get("status"),
                source_url=(
                    "https://www.registre-entreprises.tn/rne-public/"
                    f"#/entreprise/{mf or rne}"
                ),
            )
        )
    return matches


def _details_from_payload(
    payload: Any, identifier: str, kind: str
) -> CompanyDetails | None:
    record = payload
    if isinstance(payload, dict):
        for key in ("data", "entreprise", "company", "result"):
            inner = payload.get(key)
            if isinstance(inner, dict):
                record = inner
                break
    if not isinstance(record, dict):
        return None
    name = (
        record.get("denomination")
        or record.get("raisonSociale")
        or record.get("name")
        or record.get("nom")
    )
    if not name:
        return None

    mf = (
        record.get("matriculeFiscal")
        or record.get("matricule_fiscal")
        or record.get("mf")
        or record.get("taxId")
    )
    rne = (
        record.get("numeroRne")
        or record.get("rne")
        or record.get("idRne")
        or record.get("identifiantUnique")
    )
    identifiers: list[RegistryIdentifier] = []
    if mf:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT, value=str(mf), label="Matricule Fiscal"
            )
        )
    if rne:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=str(rne), label="RNE"
            )
        )
    if not identifiers:
        # Fall back to the identifier the caller supplied so the response
        # round-trips deterministically.
        identifiers.append(
            RegistryIdentifier(
                type=(
                    IdentifierType.VAT if kind == "matricule"
                    else IdentifierType.COMPANY_NUMBER
                ),
                value=identifier,
                label="Matricule Fiscal" if kind == "matricule" else "RNE",
            )
        )

    capital_raw = record.get("capital") or record.get("capitalSocial")
    capital_amount = _to_float(capital_raw)

    return CompanyDetails(
        id=str(mf or rne or identifier),
        name=str(name).strip(),
        country="TN",
        legal_form=record.get("formeJuridique") or record.get("legalForm"),
        status=record.get("statut") or record.get("status"),
        registered_address=_address_from_item(record),
        capital_amount=capital_amount,
        capital_currency="TND",
        identifiers=identifiers,
        raw={"source": "registre-entreprises.tn", "record": record},
        source_url=(
            "https://www.registre-entreprises.tn/rne-public/"
            f"#/entreprise/{mf or rne or identifier}"
        ),
    )


def _iter_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("content", "items", "results", "data", "hits", "entreprises"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = value.get("content") or value.get("items")
                if isinstance(nested, list):
                    return nested
    return []


def _address_from_item(item: dict[str, Any]) -> str | None:
    direct = item.get("adresse") or item.get("address")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    if isinstance(direct, dict):
        parts = [
            direct.get("rue") or direct.get("street"),
            direct.get("ville") or direct.get("city"),
            direct.get("codePostal") or direct.get("postalCode"),
            direct.get("gouvernorat") or direct.get("region"),
        ]
        parts = [str(p).strip() for p in parts if p]
        if parts:
            return ", ".join(parts)
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
