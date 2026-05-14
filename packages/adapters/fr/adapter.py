"""France adapter — recherche-entreprises.api.gouv.fr.

This is the official "API recherche d'entreprises" from the French government:
- Free, no auth.
- Searches and looks up SIREN/SIRET against the INSEE Sirene + INPI base.
- Pure JSON. No CAPTCHA. Documented at https://api.gouv.fr/documentation/api-recherche-entreprises

For balance sheets, the canonical source is INPI's "comptes annuels" — those
filings are public via data.inpi.fr but require OAuth. We expose the registry
data here and link out to the INPI document URL when present.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_SIREN_RE = re.compile(r"^\d{9}$")
_SIRET_RE = re.compile(r"^\d{14}$")


class FRAdapter(CountryAdapter):
    country_code = "FR"
    country_name = "France"
    identifier_types = [IdentifierType.SIREN, IdentifierType.SIRET]
    primary_identifier = IdentifierType.SIREN
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    BASE_URL = "https://recherche-entreprises.api.gouv.fr"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(client, "/search", params={"q": "total", "per_page": 1})
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            notes="Financials require INPI OAuth (not yet wired). Registry data is free.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/search", params={"q": name, "per_page": limit})
            resp.raise_for_status()
            data = resp.json()
        matches: list[CompanyMatch] = []
        for r in data.get("results", [])[:limit]:
            siren = r.get("siren")
            if not siren:
                continue
            matches.append(
                CompanyMatch(
                    id=siren,
                    name=r.get("nom_complet") or r.get("nom_raison_sociale") or "",
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.SIREN, value=siren, label="SIREN"),
                    ],
                    address=_address_from_siege(r.get("siege") or {}),
                    status=("active" if r.get("etat_administratif") == "A" else "ceased"),
                    source_url=f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        v = value.strip().replace(" ", "")
        if id_type == IdentifierType.SIREN:
            if not _SIREN_RE.match(v):
                raise InvalidIdentifierError(f"SIREN must be 9 digits: {value}")
            siren = v
        elif id_type == IdentifierType.SIRET:
            if not _SIRET_RE.match(v):
                raise InvalidIdentifierError(f"SIRET must be 14 digits: {value}")
            siren = v[:9]
        else:
            raise InvalidIdentifierError(f"FR only supports SIREN/SIRET, got {id_type}")

        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/search", params={"q": siren, "per_page": 1})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results") or []
        if not results:
            return None
        r = results[0]
        siege = r.get("siege") or {}
        directors = [
            Director(name=d.get("nom", "").strip() + " " + d.get("prenoms", "").strip())
            for d in (r.get("dirigeants") or [])
            if d.get("nom")
        ]
        inc = _parse_date(r.get("date_creation"))
        nace = r.get("activite_principale")
        return CompanyDetails(
            id=siren,
            name=r.get("nom_complet") or r.get("nom_raison_sociale") or "",
            country="FR",
            legal_form=(r.get("nature_juridique") or None),
            status=("active" if r.get("etat_administratif") == "A" else "ceased"),
            incorporation_date=inc,
            registered_address=_address_from_siege(siege),
            capital_amount=_coerce_float(r.get("capital_social")),
            capital_currency="EUR",
            nace_codes=[nace] if nace else [],
            identifiers=[
                RegistryIdentifier(type=IdentifierType.SIREN, value=siren, label="SIREN"),
            ],
            directors=directors,
            raw=r,
            source_url=f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # INPI "comptes annuels" requires OAuth. Without it, we cannot deliver
        # real PDFs in this MVP — so return empty and link out in the source_url
        # of CompanyDetails.
        return []


def _address_from_siege(siege: dict[str, Any]) -> str | None:
    parts = [
        siege.get("numero_voie"),
        siege.get("type_voie"),
        siege.get("libelle_voie"),
        siege.get("code_postal"),
        siege.get("libelle_commune"),
    ]
    s = " ".join(str(p) for p in parts if p)
    return s or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
