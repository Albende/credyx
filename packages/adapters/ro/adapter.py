"""Romania adapter — ANAF (tax authority) free VAT validator.

ANAF exposes a free, no-auth JSON endpoint that returns name, address, VAT
registration state, and fiscal flags for any Romanian CUI (Cod Unic de
Înregistrare). It is the only first-party Romanian source that offers
structured data without a paid contract or scrape — ONRC's RECOM portal
needs a commercial subscription for anything beyond a manual page view.

- Endpoint: https://webservicesp.anaf.ro/PlatitorTvaRest/api/v8/ws/tva
- Method:   POST
- Body:     `[{"cui": <int>, "data": "YYYY-MM-DD"}]` (batched, max 500/req)
- Auth:     None.
- Cost:     Free.

Financials are not exposed by ANAF. Listed companies file annual reports on
the Bucharest Stock Exchange (BVB) but only as per-company PDF/HTML, so we
return an empty list rather than fabricate a feed.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_CUI_RE = re.compile(r"^\d{2,10}$")


def _normalize_cui(value: str) -> int:
    """Strip the optional "RO" VAT prefix and any spaces, return as int.

    ANAF's API takes the CUI as a JSON integer, not a string — leading zeros
    are not used by the registry so int conversion is lossless.
    """
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned.startswith("RO"):
        cleaned = cleaned[2:]
    if not _CUI_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Romanian CUI must be 2-10 digits, got: {value}"
        )
    return int(cleaned)


class ROAdapter(CountryAdapter):
    country_code = "RO"
    country_name = "Romania"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    ANAF_URL = (
        "https://webservicesp.anaf.ro/PlatitorTvaRest/api/v8/ws/tva"
    )

    async def health_check(self) -> AdapterHealth:
        try:
            payload = self._anaf_payload(1590082)
            async with build_http_client() as client:
                resp = await client.post(self.ANAF_URL, json=payload)
                resp.raise_for_status()
                body = resp.json()
            if body.get("cod") not in (200, "200"):
                raise AdapterError(f"ANAF returned cod={body.get('cod')}")
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
            capabilities={"search": False, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via ANAF VAT validator. No free name search. "
                "Filings not exposed (BVB per-company PDFs only)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Romania has no free name-search registry. ONRC RECOM is paid; "
            "ANAF only accepts CUI lookups."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"RO only supports VAT/COMPANY_NUMBER, got {id_type}"
            )
        cui = _normalize_cui(value)
        payload = self._anaf_payload(cui)

        async with build_http_client() as client:
            resp = await client.post(self.ANAF_URL, json=payload)
            resp.raise_for_status()
            body = resp.json()

        if body.get("cod") not in (200, "200"):
            # ANAF returns cod 500/501 etc when CUI is not registered;
            # treat as "not found" rather than an error.
            return None

        found = body.get("found") or []
        if not found:
            return None
        record = found[0]
        return _details_from_anaf(record, cui)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # ANAF does not expose balance sheets; BVB annual reports are
        # per-issuer PDF pages with no machine-readable index. Without
        # introducing a scraper we cannot return real filings.
        return []

    @staticmethod
    def _anaf_payload(cui: int) -> list[dict[str, Any]]:
        return [{"cui": cui, "data": datetime.utcnow().strftime("%Y-%m-%d")}]


def _details_from_anaf(record: dict[str, Any], cui: int) -> CompanyDetails:
    """Map ANAF's nested response into CompanyDetails.

    ANAF groups fields under `date_generale`, `inregistrare_scop_Tva`,
    `inregistrare_RTVAI`, `stare_inactiv`, and `inregistrare_SplitTVA`. We
    only consume `date_generale` and the VAT-status block; the rest is
    preserved in `raw` for downstream consumers.
    """
    gen: dict[str, Any] = record.get("date_generale") or {}
    vat_block: dict[str, Any] = record.get("inregistrare_scop_Tva") or {}
    inactive_block: dict[str, Any] = record.get("stare_inactiv") or {}

    name = (gen.get("denumire") or "").strip()
    address = (gen.get("adresa") or "").strip() or None

    cui_str = str(cui)
    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=cui_str,
            label="CUI",
        ),
    ]
    if vat_block.get("scpTVA"):
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT,
                value=f"RO{cui_str}",
                label="VAT",
            )
        )

    reg_no = (gen.get("nrRegCom") or "").strip() or None
    if reg_no:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.OTHER,
                value=reg_no,
                label="ONRC registration",
            )
        )

    is_inactive = bool(inactive_block.get("statusInactivi"))
    status = "inactive" if is_inactive else "active"

    nace = (gen.get("cod_CAEN") or "").strip()
    nace_codes = [nace] if nace else []

    inc = _parse_date(gen.get("data_inregistrare"))

    phone = (gen.get("telefon") or "").strip() or None

    return CompanyDetails(
        id=cui_str,
        name=name,
        country="RO",
        legal_form=(gen.get("forma_juridica") or None),
        status=status,
        incorporation_date=inc,
        registered_address=address,
        capital_amount=None,
        capital_currency="RON",
        nace_codes=nace_codes,
        identifiers=identifiers,
        phone=phone,
        raw=record,
        source_url=(
            "https://webservicesp.anaf.ro/PlatitorTvaRest/api/v8/ws/tva"
        ),
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
