"""France adapter — recherche-entreprises.api.gouv.fr + BODACC open data.

Two free, key-free official French government sources:
- "API recherche d'entreprises" (recherche-entreprises.api.gouv.fr): search and
  SIREN/SIRET lookup against the INSEE Sirene + INPI RNE base, plus a `finances`
  block with filed revenue (CA) and net income for recent years. Pure JSON, no
  CAPTCHA. https://api.gouv.fr/documentation/api-recherche-entreprises
- BODACC (Bulletin officiel des annonces civiles et commerciales) via the
  opendatasoft Explore API: the legal gazette that publishes every "dépôt des
  comptes" (annual-accounts filing) with its closing date and a per-announcement
  URL. https://bodacc-datadila.opendatasoft.com

Financials are assembled from the BODACC accounts-filing announcements (year,
type, period end, public source URL) enriched with the real CA / net-income
figures from the recherche-entreprises `finances` block. The full comptes
annuels PDFs live behind INPI OAuth, so no `document_url` is claimed.
"""
from __future__ import annotations

import json
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
    BODACC_URL = "https://bodacc-datadila.opendatasoft.com"

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
            capabilities={"search": True, "lookup": True, "financials": True},
            notes="Registry via recherche-entreprises; accounts filings via BODACC. All key-free.",
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
        siren = company_id.strip().replace(" ", "")
        if _SIRET_RE.match(siren):
            siren = siren[:9]
        if not _SIREN_RE.match(siren):
            raise InvalidIdentifierError(f"SIREN must be 9 digits: {company_id}")

        finances = await self._fetch_finances(siren)
        deposits = await self._fetch_bodacc_deposits(siren)

        filings: list[FinancialFiling] = []
        seen: set[tuple[int, str]] = set()
        for dep in deposits:
            year = dep["year"]
            deposit_type = dep["deposit_type"]
            key = (year, deposit_type)
            if key in seen:
                continue
            seen.add(key)
            structured = {"deposit_type": deposit_type, "publication": dep["publication"]}
            structured.update(finances.get(year, {}))
            filings.append(
                FinancialFiling(
                    company_id=siren,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=dep["period_end"],
                    currency="EUR",
                    structured_data=structured or None,
                    source_url=dep["source_url"],
                )
            )

        for year, figures in finances.items():
            if any(f.year == year for f in filings):
                continue
            filings.append(
                FinancialFiling(
                    company_id=siren,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="EUR",
                    structured_data=figures or None,
                    source_url=f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}",
                )
            )

        filings.sort(key=lambda f: (f.year, f.period_end or date.min), reverse=True)
        keep_years = sorted({f.year for f in filings}, reverse=True)[:years]
        return [f for f in filings if f.year in keep_years]

    async def _fetch_finances(self, siren: str) -> dict[int, dict[str, float]]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/search", params={"q": siren, "per_page": 1})
            resp.raise_for_status()
            results = resp.json().get("results") or []
        if not results:
            return {}
        out: dict[int, dict[str, float]] = {}
        for year_str, block in (results[0].get("finances") or {}).items():
            try:
                year = int(year_str)
            except (TypeError, ValueError):
                continue
            figures: dict[str, float] = {}
            ca = _coerce_float(block.get("ca"))
            net = _coerce_float(block.get("resultat_net"))
            if ca:
                figures["revenue"] = ca
            if net:
                figures["net_income"] = net
            out[year] = figures
        return out

    async def _fetch_bodacc_deposits(self, siren: str) -> list[dict[str, Any]]:
        params = {
            "where": f"registre='{siren}' AND familleavis='dpc'",
            "limit": 100,
            "order_by": "dateparution desc",
        }
        async with build_http_client(base_url=self.BODACC_URL) as client:
            resp = await get_with_retry(
                client,
                "/api/explore/v2.1/catalog/datasets/annonces-commerciales/records",
                params=params,
            )
            resp.raise_for_status()
            records = resp.json().get("results") or []

        deposits: list[dict[str, Any]] = []
        for rec in records:
            depot = _parse_json_field(rec.get("depot"))
            period_end = _parse_date(depot.get("dateCloture"))
            if not period_end:
                continue
            deposits.append(
                {
                    "year": period_end.year,
                    "period_end": period_end,
                    "deposit_type": depot.get("typeDepot") or "Comptes annuels",
                    "publication": rec.get("dateparution"),
                    "source_url": rec.get("url_complete"),
                }
            )
        return deposits


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


def _parse_json_field(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v:
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


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
