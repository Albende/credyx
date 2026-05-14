"""Czech Republic adapter — ARES (Administrativní registr ekonomických subjektů).

Free public REST API at https://ares.gov.cz/ekonomicke-subjekty/.
Identifier: IČO, 8 digits. No auth.
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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_ICO_RE = re.compile(r"^\d{8}$")


class CZAdapter(CountryAdapter):
    country_code = "CZ"
    country_name = "Czech Republic"
    identifier_types = [IdentifierType.ICO]
    primary_identifier = IdentifierType.ICO
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                # Probe a known IČO instead of name search to avoid the POST/body
                # requirement in a health check.
                resp = await get_with_retry(client, "/ekonomicke-subjekty/45274649")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code, name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            notes="Financials available via Sbírka listin (justice.cz) — PDFs, not yet wired.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # ARES `vyhledat` is a POST endpoint with a JSON body — sending it as
        # a query-string GET returns 400.
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await client.post(
                "/ekonomicke-subjekty/vyhledat",
                json={"obchodniJmeno": name, "pocet": limit, "start": 0},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        out: list[CompanyMatch] = []
        for item in (data.get("ekonomickeSubjekty") or [])[:limit]:
            ico = item.get("ico")
            if not ico:
                continue
            out.append(
                CompanyMatch(
                    id=ico,
                    name=item.get("obchodniJmeno", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.ICO, value=ico, label="IČO"),
                    ],
                    address=_address(item.get("sidlo") or {}),
                    status=("active" if not item.get("datumZaniku") else "ceased"),
                    source_url=f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.ICO:
            raise InvalidIdentifierError("CZ only supports IČO")
        ico = value.strip().replace(" ", "").zfill(8)
        if not _ICO_RE.match(ico):
            raise InvalidIdentifierError(f"IČO must be 8 digits: {value}")
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, f"/ekonomicke-subjekty/{ico}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        pravni_forma = data.get("pravniForma")
        if isinstance(pravni_forma, dict):
            legal_form = pravni_forma.get("nazev")
        else:
            legal_form = str(pravni_forma) if pravni_forma else None
        return CompanyDetails(
            id=ico,
            name=data.get("obchodniJmeno", ""),
            country="CZ",
            legal_form=legal_form,
            status=("active" if not data.get("datumZaniku") else "ceased"),
            incorporation_date=_parse_date(data.get("datumVzniku")),
            dissolution_date=_parse_date(data.get("datumZaniku")),
            registered_address=_address(data.get("sidlo") or {}),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.ICO, value=ico, label="IČO"),
                *(
                    [RegistryIdentifier(type=IdentifierType.VAT, value=data["dic"], label="DIČ")]
                    if data.get("dic") else []
                ),
            ],
            raw=data,
            source_url=f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # CZ filings are available as PDFs in Sbírka listin on justice.cz. The
        # link is per-IČO. We return a single "discovery" pointer so the UI can
        # surface it; structured data would need PDF scraping which is outside
        # MVP scope.
        return []


def _address(s: dict[str, Any]) -> str | None:
    parts = [
        s.get("nazevUlice"),
        s.get("cisloDomovni"),
        s.get("nazevObce"),
        s.get("psc"),
    ]
    parts = [str(p) for p in parts if p]
    return " ".join(parts) or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
