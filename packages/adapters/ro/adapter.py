"""Romania adapter — ANAF (tax authority) free JSON services.

Three first-party / free sources, none needing an API key:

- **Lookup** — ANAF VAT validator. `POST` the CUI, get legal name, address,
  ONRC registration number, fiscal status, VAT flags, NACE, incorporation
  date.
  `https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva`

- **Financials** — ANAF's public balance-sheet feed (`/bilant`). `GET` with
  `an` (year) + `cui`, get the filed annual accounts as a flat list of
  Romanian statutory indicators (assets, liabilities, equity, turnover,
  profit) in RON. Data goes back years and includes the most recent filed
  fiscal year.
  `https://webservicesp.anaf.ro/bilant?an=YYYY&cui=NNN`

- **Search** — ANAF/ONRC does not expose a first-party name-search API to
  foreign IPs (mfinante.gov.ro is geoblocked). The free DemoANAF aggregator
  indexes the full ~4M-row ONRC register and returns the CUI for each hit,
  which is exactly what the lookup + financials paths need. No key,
  300 req/min.
  `https://demoanaf.ro/api/search?q=...`
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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

_CUI_RE = re.compile(r"^\d{2,10}$")

ANAF_TVA_URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
ANAF_BILANT_URL = "https://webservicesp.anaf.ro/bilant"
DEMOANAF_SEARCH_URL = "https://demoanaf.ro/api/search"


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

    async def health_check(self) -> AdapterHealth:
        try:
            payload = self._anaf_payload(1590082)
            async with build_http_client() as client:
                resp = await client.post(ANAF_TVA_URL, json=payload)
                resp.raise_for_status()
                body = resp.json()
            if "found" not in body:
                raise AdapterError(f"ANAF returned unexpected shape: {list(body)}")
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
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup + financials via ANAF (VAT validator + /bilant). "
                "Name search via DemoANAF ONRC index."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with build_http_client() as client:
            resp = await get_with_retry(
                client, DEMOANAF_SEARCH_URL, params={"q": query}
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            body = resp.json()

        if not body.get("success"):
            raise AdapterError(f"DemoANAF search failed: {str(body)[:200]}")
        rows = body.get("data") or []
        return [_match_from_demoanaf(row) for row in rows[:limit]]

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
            resp = await client.post(ANAF_TVA_URL, json=payload)
            # v9 answers HTTP 404 (with a valid JSON body) when the CUI is
            # not registered — only treat other errors as failures.
            if resp.status_code != 404:
                resp.raise_for_status()
            body = resp.json()

        found = body.get("found") or []
        if not found:
            return None
        return _details_from_anaf(found[0], cui)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cui = _normalize_cui(company_id)
        cui_str = str(cui)
        current_year = datetime.utcnow().year

        filings: list[FinancialFiling] = []
        async with build_http_client() as client:
            for an in range(current_year, current_year - years - 2, -1):
                if len(filings) >= years:
                    break
                resp = await get_with_retry(
                    client, ANAF_BILANT_URL, params={"an": an, "cui": cui}
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                body = resp.json()
                indicators = body.get("i") or []
                if not indicators:
                    continue
                filings.append(_filing_from_bilant(body, cui_str, an))
        return filings

    @staticmethod
    def _anaf_payload(cui: int) -> list[dict[str, Any]]:
        return [{"cui": cui, "data": datetime.utcnow().strftime("%Y-%m-%d")}]


def _match_from_demoanaf(row: dict[str, Any]) -> CompanyMatch:
    cui_str = str(row.get("cui") or "").strip()
    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=cui_str, label="CUI"
        )
    ]
    reg_no = (row.get("registrationNumber") or "").strip()
    if reg_no:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.OTHER, value=reg_no, label="ONRC registration"
            )
        )

    locality = (row.get("locality") or "").strip()
    county = (row.get("county") or "").strip()
    address = ", ".join(part for part in (locality, county) if part) or None

    label = (row.get("statusLabel") or "").strip()
    status = _STATUS_LABELS.get(_strip_diacritics(label).lower(), label or None)

    return CompanyMatch(
        id=cui_str,
        name=(row.get("name") or "").strip(),
        country="RO",
        identifiers=identifiers,
        address=address,
        status=status,
        source_url=DEMOANAF_SEARCH_URL,
    )


_STATUS_LABELS = {
    "functiune": "active",
    "radiata": "dissolved",
    "insolventa": "insolvent",
    "dizolvare": "dissolving",
    "lichidare": "liquidation",
}


def _details_from_anaf(record: dict[str, Any], cui: int) -> CompanyDetails:
    """Map ANAF's nested VAT-validator response into CompanyDetails."""
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
        source_url=ANAF_TVA_URL,
    )


# ANAF `/bilant` reports the Romanian statutory indicator set. The I-codes are
# not stable across taxonomies (banks/insurers use a different chart), so we
# map by the label text, not the code. Anything we can't confidently match
# stays out of the typed sections and is preserved under `raw_concepts`.
_BALANCE_MATCHERS: dict[str, tuple[str, ...]] = {
    "non_current_assets": ("active imobilizate",),
    "current_assets": ("active circulante",),
    "inventories": ("stocuri",),
    "trade_receivables": ("creante",),
    "cash_and_equivalents": ("casa si conturi la banci",),
    "total_liabilities": ("datorii",),
    "total_equity": ("capitaluri",),
    "share_capital": ("capital subscris varsat",),
}
_INCOME_MATCHERS: dict[str, tuple[str, ...]] = {
    "revenue": ("cifra de afaceri neta",),
}


def _filing_from_bilant(body: dict[str, Any], cui: str, year: int) -> FinancialFiling:
    indicators = body.get("i") or []
    values: dict[str, float] = {}
    raw_concepts: dict[str, Any] = {}
    net_profit = net_loss = prepaid = None
    for item in indicators:
        label = _strip_diacritics(str(item.get("val_den_indicator") or "")).lower().strip()
        val = item.get("val_indicator")
        code = str(item.get("indicator") or "")
        raw_concepts[code] = {"label": item.get("val_den_indicator"), "value": val}
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        num = float(val)
        for key, needles in _BALANCE_MATCHERS.items():
            if key not in values and any(n in label for n in needles):
                values[key] = num
        for key, needles in _INCOME_MATCHERS.items():
            if key not in values and any(n in label for n in needles):
                values[key] = num
        if label.startswith("cheltuieli in avans"):
            prepaid = num
        elif label.startswith("profit net"):
            net_profit = num
        elif label.startswith("pierdere neta"):
            net_loss = num

    balance_sheet = {
        k: values[k]
        for k in _BALANCE_MATCHERS
        if k in values
    }
    non_current = balance_sheet.get("non_current_assets")
    current = balance_sheet.get("current_assets")
    if non_current is not None and current is not None:
        balance_sheet["total_assets"] = non_current + current + (prepaid or 0.0)

    income_statement: dict[str, float] = {
        k: values[k] for k in _INCOME_MATCHERS if k in values
    }
    if net_profit:
        income_statement["net_income"] = net_profit
    elif net_loss:
        income_statement["net_income"] = -net_loss

    structured = {
        "currency": "RON",
        "period_end": f"{year}-12-31",
        "consolidated": False,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "caen": body.get("caen"),
        "caen_description": body.get("den_caen"),
        "raw_concepts": raw_concepts,
    }

    source_url = f"{ANAF_BILANT_URL}?an={year}&cui={cui}"
    return FinancialFiling(
        company_id=cui,
        year=year,
        type=FilingType.ANNUAL_REPORT,
        period_end=date(year, 12, 31),
        currency="RON",
        structured_data=structured,
        document_url=source_url,
        document_format="json",
        source_url=source_url,
    )


def _strip_diacritics(value: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
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
