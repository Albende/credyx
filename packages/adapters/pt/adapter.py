"""Portugal adapter — VIES lookup + GLEIF search + ESEF financial filings.

Portugal has no free authoritative name-search API of its own. The Instituto
dos Registos e do Notariado (IRN / Registo Comercial Online) charges per
certificate, and Portal da Empresa exposes only an interactive web search
behind a CAPTCHA — neither qualifies as a free machine-readable source.

What is free and usable:

- VIES (EU VAT Information Exchange, REST) confirms a Portuguese NIPC is a
  valid VAT registration and returns the registered name + address.
- GLEIF (Global LEI Foundation, JSON:API) offers free full-text company
  search scoped to Portugal and maps a NIPC to the entity's LEI via the
  `registeredAs` field. Coverage is limited to LEI-holding entities
  (listed issuers, funds, regulated and securities-trading firms).
- filings.xbrl.org publishes every EU-listed issuer's ESEF annual financial
  report (inline XBRL) keyed by LEI, at no cost. These are the real filed
  accounts, not a landing page.

So `search_by_name` queries GLEIF full-text (PT-scoped); `lookup_by_identifier`
validates the NIPC via VIES and enriches it with the LEI from GLEIF;
`fetch_financials` resolves the NIPC to a LEI and returns the actual ESEF
report documents filed by that specific company.

NIPC format: 9 digits. Check digit (last) is computed from the first 8
digits with weights 9, 8, 7, 6, 5, 4, 3, 2; sum mod 11; if remainder is
0 or 1 the check digit is 0, else 11 - remainder.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

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

_NIPC_RE = re.compile(r"^\d{9}$")

# EDP, S.A.: a stable, always-valid NIPC used as a VIES liveness probe.
_VIES_HEALTH_PROBE = "500697256"


def _normalize_nipc(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("PT"):
        cleaned = cleaned[2:]
    if not _NIPC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Portuguese NIPC must be 9 digits: {value}"
        )
    if not _nipc_checksum_ok(cleaned):
        raise InvalidIdentifierError(f"Portuguese NIPC checksum invalid: {value}")
    return cleaned


def _nipc_checksum_ok(nipc: str) -> bool:
    weights = (9, 8, 7, 6, 5, 4, 3, 2)
    total = sum(int(nipc[i]) * weights[i] for i in range(8))
    remainder = total % 11
    expected = 0 if remainder < 2 else 11 - remainder
    return int(nipc[8]) == expected


class PTAdapter(CountryAdapter):
    country_code = "PT"
    country_name = "Portugal"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_REST_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/PT/vat"
    GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
    FILINGS_BASE = "https://filings.xbrl.org"

    async def health_check(self) -> AdapterHealth:
        try:
            payload = await self._vies_check(_VIES_HEALTH_PROBE)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if not payload or not payload.get("valid"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="VIES reachable but EDP NIPC reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via VIES; PT-scoped name search via GLEIF; ESEF "
                "financial filings via filings.xbrl.org (LEI-holding issuers)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = name.strip()
        if not term:
            raise InvalidIdentifierError("Empty search term")
        records = await self._gleif_query(
            {
                "filter[fulltext]": term,
                "filter[entity.legalAddress.country]": "PT",
                "page[size]": max(1, min(int(limit), 50)),
                "page[number]": 1,
            }
        )
        matches = [self._gleif_record_to_match(r) for r in records]
        matches = [m for m in matches if m is not None]
        if not matches:
            raise AdapterNotImplementedError(
                f"No PT entity with an LEI matched '{name}'. GLEIF only covers "
                "LEI-holding companies (listed issuers, funds, regulated firms). "
                "Portugal has no free authoritative full-registry name search — "
                "Registo Comercial Online charges per certificate and Portal da "
                "Empresa is CAPTCHA-gated. Look up directly by NIPC/VAT instead."
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"PT supports VAT/COMPANY_NUMBER, got {id_type}"
            )
        nipc = _normalize_nipc(value)
        vies = await self._vies_check(nipc)
        if not vies or not vies.get("valid"):
            return None

        gleif = await self._gleif_by_nipc(nipc)
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=nipc, label="NIPC"
            ),
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"PT{nipc}", label="VAT"
            ),
        ]
        lei = None
        legal_form = None
        gleif_address = None
        if gleif:
            entity = (gleif.get("attributes") or {}).get("entity") or {}
            lei = gleif.get("id") or (gleif.get("attributes") or {}).get("lei")
            legal_form = _safe_get(entity, "legalForm", "id")
            gleif_address = _format_gleif_address(entity.get("legalAddress"))
            if lei:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.LEI, value=str(lei), label="LEI"
                    )
                )

        return CompanyDetails(
            id=nipc,
            name=(vies.get("name") or "").strip() or nipc,
            country="PT",
            legal_form=str(legal_form) if legal_form else None,
            status="active",
            registered_address=(
                (vies.get("address") or "").strip() or gleif_address or None
            ),
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": vies, "gleif_lei": lei},
            source_url=(
                f"https://search.gleif.org/#/record/{lei}" if lei else None
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        nipc = _normalize_nipc(company_id)
        gleif = await self._gleif_by_nipc(nipc)
        if not gleif:
            return []
        lei = gleif.get("id") or (gleif.get("attributes") or {}).get("lei")
        if not lei:
            return []

        filings_raw = await self._xbrl_filings_for_lei(str(lei))
        filings: list[FinancialFiling] = []
        for attrs in filings_raw:
            period_end_raw = attrs.get("period_end")
            report_url = attrs.get("report_url")
            if not period_end_raw or not report_url:
                continue
            try:
                period_end = date.fromisoformat(period_end_raw)
            except ValueError:
                continue
            viewer_url = attrs.get("viewer_url")
            filings.append(
                FinancialFiling(
                    company_id=nipc,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="EUR",
                    structured_data=None,
                    document_url=f"{self.FILINGS_BASE}{report_url}",
                    document_format="xbrl",
                    source_url=(
                        f"{self.FILINGS_BASE}{viewer_url}"
                        if viewer_url
                        else f"{self.FILINGS_BASE}/api/entities/{lei}"
                    ),
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings[: max(1, years)] if filings else []

    async def _vies_check(self, nipc: str) -> dict[str, Any] | None:
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/json"}
        ) as client:
            resp = await get_with_retry(client, f"{self.VIES_REST_URL}/{nipc}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        return {
            "valid": bool(data.get("isValid")),
            "name": data.get("name") or "",
            "address": (data.get("address") or "").replace("\n", ", "),
            "user_error": data.get("userError"),
        }

    async def _gleif_query(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/vnd.api+json"}
        ) as client:
            resp = await get_with_retry(client, self.GLEIF_URL, params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("data") or []

    async def _gleif_by_nipc(self, nipc: str) -> dict[str, Any] | None:
        records = await self._gleif_query(
            {
                "filter[entity.registeredAs]": nipc,
                "filter[entity.legalAddress.country]": "PT",
                "page[size]": 1,
            }
        )
        return records[0] if records else None

    async def _xbrl_filings_for_lei(self, lei: str) -> list[dict[str, Any]]:
        url = f"{self.FILINGS_BASE}/api/entities/{lei}"
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/vnd.api+json"}
        ) as client:
            resp = await get_with_retry(
                client, url, params={"include": "filings"}
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        included = payload.get("included") or []
        return [
            item.get("attributes") or {}
            for item in included
            if item.get("type") == "filing"
        ]

    def _gleif_record_to_match(
        self, record: dict[str, Any]
    ) -> CompanyMatch | None:
        lei = record.get("id") or (record.get("attributes") or {}).get("lei")
        if not lei:
            return None
        entity = (record.get("attributes") or {}).get("entity") or {}
        name = _safe_get(entity, "legalName", "name")
        if not name:
            return None
        nipc = entity.get("registeredAs")
        identifiers = [
            RegistryIdentifier(type=IdentifierType.LEI, value=str(lei), label="LEI")
        ]
        if nipc:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=str(nipc),
                    label="NIPC",
                )
            )
        status_raw = (entity.get("status") or "").upper()
        return CompanyMatch(
            id=str(nipc) if nipc else str(lei),
            name=str(name),
            country="PT",
            identifiers=identifiers,
            address=_format_gleif_address(entity.get("legalAddress")),
            status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
            source_url=f"https://search.gleif.org/#/record/{lei}",
        )


def _safe_get(obj: Any, *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _format_gleif_address(address: Any) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    for key in ("city", "region", "postalCode", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None
