"""Latvia adapter — Uzņēmumu reģistrs (UR) open data + VIES.

Free, public, key-free Latvian sources:

- The Enterprise Register (UR) publishes its full open data at
  ``https://dati.ur.gov.lv/``. ``register/register.csv`` lists every legal
  entity (regcode, name, legal form, address, registration / termination
  dates); we stream it and filter in memory — there is no per-company JSON
  endpoint. (The older data.gov.lv CKAN download URL 404s as of 2026; the
  register lives on dati.ur.gov.lv now.)
- Latvia is unusual in publishing the *financial content* of filed annual
  reports as open data too. ``financial_data/financial_statements.csv``
  indexes every filed statement (regcode, year, period, currency, filing
  type); ``balance_sheets.csv`` and ``income_statements.csv`` carry the
  actual line items, joined by ``file_id``. ``fetch_financials`` streams
  these and returns real ``FinancialFiling`` records with structured data
  for the specific company — never mock numbers.
- VIES resolves an LV VAT (``LV`` + 11 digits) to a name + address.

Identifier scope:
- COMPANY_NUMBER → ``reģistrācijas numurs``, 11 digits.
- VAT             → ``LV`` + 11 digits.

If a source becomes unreachable or its schema changes, callers see the
underlying httpx error or an empty result — we never fabricate data.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable

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

_REGCODE_RE = re.compile(r"^\d{11}$")
_LV_VAT_RE = re.compile(r"^\d{11}$")

_VIES_ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:checkVat>
      <urn:countryCode>{cc}</urn:countryCode>
      <urn:vatNumber>{vat}</urn:vatNumber>
    </urn:checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""

_VIES_NS = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "vies": "urn:ec.europa.eu:taxud:vies:services:checkVat:types",
}

_ROUNDING_FACTORS: dict[str, int] = {"ONES": 1, "THOUSANDS": 1_000, "MILLIONS": 1_000_000}


def _normalize_regcode(value: str) -> str:
    """Return a canonical 11-digit Latvian reģistrācijas numurs."""
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("LV"):
        cleaned = cleaned[2:]
    if not _REGCODE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Latvian reģistrācijas numurs must be 11 digits: {value}"
        )
    return cleaned


def _normalize_lv_vat(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("LV"):
        cleaned = cleaned[2:]
    if not _LV_VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Latvian VAT must be 'LV' + 11 digits: {value}"
        )
    return cleaned


class LVAdapter(CountryAdapter):
    country_code = "LV"
    country_name = "Latvia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    REGISTER_CSV_URL = "https://dati.ur.gov.lv/register/register.csv"
    FINANCIAL_STATEMENTS_CSV_URL = (
        "https://dati.ur.gov.lv/financial_data/financial_statements.csv"
    )
    BALANCE_SHEETS_CSV_URL = "https://dati.ur.gov.lv/financial_data/balance_sheets.csv"
    INCOME_STATEMENTS_CSV_URL = (
        "https://dati.ur.gov.lv/financial_data/income_statements.csv"
    )
    UR_PUBLIC_PAGE = "https://www.ur.gov.lv/lv/uznemumu-meklesana/"

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._vies_client() as client:
                resp = await client.post(
                    self.VIES_URL,
                    content=_VIES_ENVELOPE.format(cc="LV", vat="40003032949"),
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if resp.status_code >= 500:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES returned HTTP {resp.status_code}.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search/lookup via dati.ur.gov.lv UR open-data CSV; VAT via VIES; "
                "financials from the UR financial_data open dataset."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = (name or "").strip().lower()
        if not needle:
            return []
        try:
            rows = await self._fetch_register_csv()
        except httpx.HTTPError:
            return []
        matches: list[CompanyMatch] = []
        for row in rows:
            row_name = (row.get("name") or "").strip()
            if not row_name or needle not in row_name.lower():
                continue
            regcode = (row.get("regcode") or "").strip()
            if not regcode:
                continue
            matches.append(_match_from_row(regcode, row_name, row))
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_regcode(value)
        raise InvalidIdentifierError(
            f"LV supports COMPANY_NUMBER (reģistrācijas numurs) or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        regcode = _normalize_regcode(company_id)
        statements = await self._fetch_statement_index(regcode)
        if not statements:
            return []
        statements.sort(key=lambda s: (s["year"], s["id"]), reverse=True)
        selected = statements[: max(years, 1)]
        file_ids = {s["file_id"] for s in selected}
        balances = await self._fetch_line_items(self.BALANCE_SHEETS_CSV_URL, file_ids)
        incomes = await self._fetch_line_items(self.INCOME_STATEMENTS_CSV_URL, file_ids)
        filings: list[FinancialFiling] = []
        for stmt in selected:
            filings.append(
                _filing_from_statement(
                    regcode,
                    stmt,
                    balances.get(stmt["file_id"]),
                    incomes.get(stmt["file_id"]),
                    self.FINANCIAL_STATEMENTS_CSV_URL,
                )
            )
        return filings

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_lv_vat(value)
        result = await self._vies_check(vat)
        if not result or not result.get("valid"):
            return None
        identifiers = [
            RegistryIdentifier(type=IdentifierType.VAT, value=f"LV{vat}", label="PVN numurs"),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=vat,
                label="Reģistrācijas numurs",
            ),
        ]
        return CompanyDetails(
            id=f"LV{vat}",
            name=(result.get("name") or "").strip() or f"LV{vat}",
            country="LV",
            status="active",
            registered_address=(result.get("address") or "").strip() or None,
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"vies": result},
            source_url=None,
        )

    async def _lookup_by_regcode(self, value: str) -> CompanyDetails | None:
        regcode = _normalize_regcode(value)
        try:
            rows = await self._fetch_register_csv()
        except httpx.HTTPError:
            return None
        for row in rows:
            if (row.get("regcode") or "").strip() == regcode:
                return _details_from_row(regcode, row)
        return None

    async def _fetch_register_csv(self) -> list[dict[str, str]]:
        """Stream the UR open-data register CSV and return its rows as dicts.

        Names and addresses are quoted and may contain embedded newlines, so
        the whole document is parsed by ``csv`` rather than split by line.
        """
        async with build_http_client(timeout=180.0) as client:
            resp = await get_with_retry(client, self.REGISTER_CSV_URL)
            resp.raise_for_status()
            text = resp.text
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        return [_normalize_row(r) for r in reader]

    async def _fetch_statement_index(self, regcode: str) -> list[dict[str, Any]]:
        """Return this company's filed-statement index rows.

        ``legal_entity_registration_number`` is the join key back to the
        register; each row carries the ``file_id`` used to pull line items.
        """
        needle = f";{regcode};"
        out: list[dict[str, Any]] = []
        async for row in _stream_semicolon_csv(
            self.FINANCIAL_STATEMENTS_CSV_URL, lambda line: needle in line
        ):
            if row.get("legal_entity_registration_number") != regcode:
                continue
            year = _to_int(row.get("year"))
            file_id = (row.get("file_id") or "").strip()
            if year is None or not file_id:
                continue
            out.append(
                {
                    "id": (row.get("id") or "").strip(),
                    "file_id": file_id,
                    "year": year,
                    "period_start": (row.get("year_started_on") or "").strip() or None,
                    "period_end": (row.get("year_ended_on") or "").strip() or None,
                    "currency": (row.get("currency") or "").strip() or None,
                    "rounding": (row.get("rounded_to_nearest") or "").strip().upper(),
                    "employees": _to_int(row.get("employees")),
                    "source_type": (row.get("source_type") or "").strip() or None,
                    "source_schema": (row.get("source_schema") or "").strip() or None,
                }
            )
        return out

    async def _fetch_line_items(
        self, url: str, file_ids: set[str]
    ) -> dict[str, dict[str, str]]:
        """Stream a line-item CSV, keyed by ``file_id`` for the wanted rows."""
        if not file_ids:
            return {}
        wanted = {f";{fid};" for fid in file_ids}
        out: dict[str, dict[str, str]] = {}

        def keep(line: str) -> bool:
            return any(token in line for token in wanted)

        async for row in _stream_semicolon_csv(url, keep):
            fid = (row.get("file_id") or "").strip()
            if fid in file_ids:
                out[fid] = row
        return out

    async def _vies_check(self, vat: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="LV", vat=vat)
        async with self._vies_client() as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)

    def _vies_client(self) -> httpx.AsyncClient:
        return build_http_client(
            timeout=30.0,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        )


async def _stream_semicolon_csv(
    url: str, keep: Callable[[str], bool]
) -> Any:
    """Yield ``dict`` rows from a large ``;``-delimited numeric CSV.

    The financial datasets are purely numeric with no quoting or embedded
    newlines, so a line-oriented stream with a cheap substring pre-filter
    lets us scan a 200 MB file without holding it in memory.
    """
    header: list[str] | None = None
    async with build_http_client(timeout=300.0) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if header is None:
                    header = line.split(";")
                    continue
                if not keep(line):
                    continue
                values = line.split(";")
                yield dict(zip(header, values))


# data.gov.lv occasionally varies column casing across snapshots; normalize
# the keys we care about to a stable lower-case set.
_COLUMN_ALIASES: dict[str, str] = {
    "regcode": "regcode",
    "regcods": "regcode",
    "regnumber": "regcode",
    "regnr": "regcode",
    "name": "name",
    "name_before_quotes": "legal_form",
    "name_in_quotes": "name_short",
    "type": "type_code",
    "type_text": "legal_form_text",
    "registered": "registered",
    "registration_date": "registered",
    "terminated": "terminated",
    "address": "address",
    "addresses": "address",
    "address_full": "address",
    "index": "postal_code",
    "addresses_index": "postal_code",
}


def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        norm_key = _COLUMN_ALIASES.get(key.strip().lower(), key.strip().lower())
        if value is None:
            continue
        if norm_key not in out or not out[norm_key]:
            out[norm_key] = value.strip()
    return out


def _legal_form(row: dict[str, str]) -> str | None:
    return (row.get("legal_form_text") or row.get("type_code") or "").strip() or None


def _match_from_row(regcode: str, row_name: str, row: dict[str, str]) -> CompanyMatch:
    return CompanyMatch(
        id=regcode,
        name=row_name,
        country="LV",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=regcode,
                label="Reģistrācijas numurs",
            )
        ],
        address=_address_from_row(row),
        status=_status_from_row(row),
        source_url=LVAdapter.UR_PUBLIC_PAGE,
    )


def _details_from_row(regcode: str, row: dict[str, str]) -> CompanyDetails:
    name = (row.get("name") or row.get("name_short") or "").strip()
    return CompanyDetails(
        id=regcode,
        name=name or regcode,
        country="LV",
        legal_form=_legal_form(row),
        status=_status_from_row(row),
        registered_address=_address_from_row(row),
        capital_currency="EUR",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=regcode,
                label="Reģistrācijas numurs",
            ),
        ],
        raw={"ur_row": row},
        source_url=LVAdapter.UR_PUBLIC_PAGE,
    )


def _address_from_row(row: dict[str, str]) -> str | None:
    parts = [row.get("address"), row.get("postal_code")]
    joined = ", ".join(p.strip() for p in parts if p and p.strip())
    return joined or None


def _status_from_row(row: dict[str, str]) -> str | None:
    terminated = (row.get("terminated") or "").strip()
    if terminated:
        return f"terminated:{terminated}"
    if (row.get("registered") or "").strip():
        return "active"
    return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _scaled(value: str | None, factor: int) -> float | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned) * factor
    except ValueError:
        return None


_BALANCE_MAP: dict[str, str] = {
    "cash_and_equivalents": "cash",
    "trade_receivables": "accounts_receivable",
    "inventories": "inventories",
    "current_assets": "total_current_assets",
    "non_current_assets": "total_non_current_assets",
    "total_assets": "total_assets",
    "current_liabilities": "current_liabilities",
    "non_current_liabilities": "non_current_liabilities",
    "total_equity": "equity",
}

_INCOME_MAP: dict[str, str] = {
    "revenue": "net_turnover",
    "gross_profit": "by_function_gross_profit",
    "depreciation_amortization": "by_nature_depreciation_expenses",
    "interest_expense": "interest_expenses",
    "net_income": "net_income",
}


def _build_balance_sheet(
    row: dict[str, str] | None, factor: int
) -> dict[str, float]:
    if not row:
        return {}
    out: dict[str, float] = {}
    for target, source in _BALANCE_MAP.items():
        scaled = _scaled(row.get(source), factor)
        if scaled is not None:
            out[target] = scaled
    equity = _scaled(row.get("equity"), factor)
    total_assets = _scaled(row.get("total_assets"), factor)
    if equity is not None and total_assets is not None:
        out["total_liabilities"] = total_assets - equity
    return out


def _build_income_statement(
    row: dict[str, str] | None, factor: int
) -> dict[str, float]:
    if not row:
        return {}
    out: dict[str, float] = {}
    for target, source in _INCOME_MAP.items():
        scaled = _scaled(row.get(source), factor)
        if scaled is not None:
            out[target] = scaled
    return out


def _filing_from_statement(
    regcode: str,
    stmt: dict[str, Any],
    balance_row: dict[str, str] | None,
    income_row: dict[str, str] | None,
    dataset_url: str,
) -> FinancialFiling:
    factor = _ROUNDING_FACTORS.get(stmt["rounding"], 1)
    consolidated = (stmt.get("source_type") or "").upper() in {"UKGP", "KGP"}
    balance_sheet = _build_balance_sheet(balance_row, factor)
    income_statement = _build_income_statement(income_row, factor)
    structured: dict[str, Any] = {
        "currency": stmt.get("currency"),
        "period_end": stmt.get("period_end"),
        "consolidated": consolidated,
        "raw_concepts": {
            "file_id": stmt["file_id"],
            "source_type": stmt.get("source_type"),
            "source_schema": stmt.get("source_schema"),
            "rounded_to_nearest": stmt.get("rounding"),
            "employees": stmt.get("employees"),
        },
    }
    if balance_sheet:
        structured["balance_sheet"] = balance_sheet
    if income_statement:
        structured["income_statement"] = income_statement
    period_end = _parse_date(stmt.get("period_end"))
    return FinancialFiling(
        company_id=regcode,
        year=stmt["year"],
        type=FilingType.ANNUAL_REPORT,
        period_end=period_end,
        currency=stmt.get("currency"),
        structured_data=structured if (balance_sheet or income_statement) else None,
        document_url=None,
        document_format="json",
        source_url=dataset_url,
    )


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        from datetime import date

        parts = value.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def _parse_vies_response(xml_text: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    body = root.find("soap:Body", _VIES_NS)
    if body is None:
        return None
    fault = body.find("soap:Fault", _VIES_NS)
    if fault is not None:
        return {"valid": False, "fault": (fault.findtext("faultstring") or "").strip()}
    resp = body.find("vies:checkVatResponse", _VIES_NS)
    if resp is None:
        return None
    valid = (
        resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or ""
    ).lower() == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}
