"""Brazil adapter — Receita Federal CNPJ data plus CVM listed-company filings.

Sources:
- Name search: DadosBrasil open API
  https://api.dadosbrasil.net/api/v1/companies?q={term} — free, no auth,
  full Receita Federal CNPJ open dataset re-imported monthly.
- Lookup by CNPJ: BrasilAPI https://brasilapi.com.br/api/cnpj/v1/{cnpj}
  (free, no auth, ~3 req/s) with ReceitaWS
  https://www.receitaws.com.br/v1/cnpj/{cnpj} as a 5xx fallback.
- Listed-company financials: CVM (Comissão de Valores Mobiliários) DFP
  open data. The cadastro CSV maps CNPJ → CVM code; the yearly DFP bundle
  https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip
  carries the per-company filing index (with the official document link)
  and the structured balance-sheet / income-statement line items.

Identifier: CNPJ (14 digits, format XX.XXX.XXX/XXXX-XX). CNPJ doubles as
the Brazilian corporate tax ID; there is no separate VAT number, so we
expose it as the primary VAT and also accept COMPANY_NUMBER.
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    InvalidIdentifierError,
)
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

_DIGITS_RE = re.compile(r"\D+")
_CNPJ_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_WEIGHTS_2 = [6] + _CNPJ_WEIGHTS_1

_DB_UNAVAILABLE = "database temporarily unavailable"

# CVM DFP standardized account codes → unified financial-statement keys the
# risk engine reads (packages/risk/ratios.py).
_BPA_ACCOUNTS = {
    "1": "total_assets",
    "1.01": "current_assets",
    "1.01.01": "cash_and_equivalents",
    "1.02": "non_current_assets",
}
_BPP_ACCOUNTS = {
    "2.01": "current_liabilities",
    "2.02": "non_current_liabilities",
    "2.03": "total_equity",
}
_DRE_ACCOUNTS = {
    "3.01": "revenue",
    "3.03": "gross_profit",
    "3.05": "operating_profit",
    "3.11": "net_income",
}


def _normalize_cnpj(value: str) -> str:
    cleaned = _DIGITS_RE.sub("", value or "")
    if len(cleaned) != 14:
        raise InvalidIdentifierError(f"CNPJ must be 14 digits: {value}")
    if cleaned == cleaned[0] * 14:
        raise InvalidIdentifierError(f"CNPJ cannot be all identical digits: {value}")
    if not _cnpj_check_digits_valid(cleaned):
        raise InvalidIdentifierError(f"CNPJ check digits invalid: {value}")
    return cleaned


def _cnpj_check_digits_valid(cnpj: str) -> bool:
    def _dv(base: str, weights: list[int]) -> int:
        total = sum(int(d) * w for d, w in zip(base, weights))
        rem = total % 11
        return 0 if rem < 2 else 11 - rem

    dv1 = _dv(cnpj[:12], _CNPJ_WEIGHTS_1)
    dv2 = _dv(cnpj[:12] + str(dv1), _CNPJ_WEIGHTS_2)
    return cnpj[-2:] == f"{dv1}{dv2}"


def _format_cnpj(cnpj: str) -> str:
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


class BRAdapter(CountryAdapter):
    country_code = "BR"
    country_name = "Brazil"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    BRASILAPI_BASE = "https://brasilapi.com.br"
    RECEITAWS_BASE = "https://www.receitaws.com.br"
    DADOSBRASIL_BASE = "https://api.dadosbrasil.net"
    CVM_CADASTRO_URL = (
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    )
    CVM_DFP_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS"

    # Petrobras — used as the canonical health-check CNPJ.
    _HEALTH_CNPJ = "33000167000101"

    def __init__(self) -> None:
        self._cvm_cache: dict[str, str] | None = None
        self._cvm_lock = asyncio.Lock()

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BRASILAPI_BASE) as client:
                resp = await get_with_retry(
                    client, f"/api/cnpj/v1/{self._HEALTH_CNPJ}"
                )
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
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search via DadosBrasil open data (Receita Federal CNPJ). "
                "Financials limited to CVM-listed companies (structured DFP "
                "line items)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = (name or "").strip()
        if not term:
            return []
        path = f"/api/v1/companies?q={quote(term)}&limit={max(1, min(limit, 50))}"
        payload = await self._dadosbrasil_get(path)
        if not payload:
            return []
        matches: list[CompanyMatch] = []
        for item in payload.get("items") or []:
            match = _match_from_dadosbrasil(item)
            if match is not None:
                matches.append(match)
        return matches

    async def _dadosbrasil_get(self, path: str) -> dict[str, Any] | None:
        # The DadosBrasil server intermittently reports its backend as
        # unavailable — sometimes as a JSON error, sometimes by stalling the
        # connection until it read-times-out. Retry both across fresh clients.
        for attempt in range(8):
            try:
                async with build_http_client(
                    base_url=self.DADOSBRASIL_BASE, timeout=12.0
                ) as client:
                    resp = await client.get(path)
            except httpx.HTTPError:
                await asyncio.sleep(0.8)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 500:
                await asyncio.sleep(0.8)
                continue
            try:
                data = resp.json()
            except ValueError:
                await asyncio.sleep(0.8)
                continue
            if isinstance(data, dict) and data.get("error") == _DB_UNAVAILABLE:
                await asyncio.sleep(0.8)
                continue
            return data if isinstance(data, dict) else None
        return None

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"BR only supports VAT/COMPANY_NUMBER (CNPJ), got {id_type}"
            )
        cnpj = _normalize_cnpj(value)

        data = await self._fetch_brasilapi(cnpj)
        if data is None:
            data = await self._fetch_receitaws(cnpj)
        if data is None:
            return None
        return _details_from_payload(cnpj, data)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cnpj = _normalize_cnpj(company_id)
        if await self._cvm_code_for(cnpj) is None:
            return []

        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for ref_year in range(current_year, current_year - (years + 2), -1):
            if len(filings) >= years:
                break
            filing = await self._dfp_filing(cnpj, ref_year)
            if filing is not None:
                filings.append(filing)
        return filings

    async def _dfp_filing(self, cnpj: str, year: int) -> FinancialFiling | None:
        zip_url = f"{self.CVM_DFP_BASE}/dfp_cia_aberta_{year}.zip"
        try:
            async with build_http_client(timeout=90.0) as client:
                resp = await get_with_retry(client, zip_url)
                if resp.status_code != 200:
                    return None
                raw = resp.content
        except httpx.HTTPError:
            return None
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return None

        index_row = _find_dfp_index_row(zf, f"dfp_cia_aberta_{year}.csv", cnpj)
        if index_row is None:
            return None

        structured = _parse_dfp_statements(zf, year, cnpj, "con")
        if not structured:
            structured = _parse_dfp_statements(zf, year, cnpj, "ind")

        period_end = _parse_date(index_row.get("DT_REFER")) or date(year, 12, 31)
        link = (index_row.get("LINK_DOC") or "").strip() or None
        return FinancialFiling(
            company_id=cnpj,
            year=period_end.year,
            type=FilingType.ANNUAL_REPORT,
            period_end=period_end,
            currency="BRL",
            structured_data=structured or None,
            document_url=link,
            document_format="zip" if link else None,
            source_url=zip_url,
        )

    async def _fetch_brasilapi(self, cnpj: str) -> dict[str, Any] | None:
        try:
            async with build_http_client(base_url=self.BRASILAPI_BASE) as client:
                resp = await get_with_retry(client, f"/api/cnpj/v1/{cnpj}")
                if resp.status_code == 404:
                    return None
                if resp.status_code >= 500:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError:
            return None

    async def _fetch_receitaws(self, cnpj: str) -> dict[str, Any] | None:
        try:
            async with build_http_client(base_url=self.RECEITAWS_BASE) as client:
                resp = await get_with_retry(client, f"/v1/cnpj/{cnpj}")
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError:
            return None
        if isinstance(payload, dict) and payload.get("status") == "ERROR":
            return None
        return _receitaws_to_brasilapi_shape(payload)

    async def _cvm_code_for(self, cnpj: str) -> str | None:
        cache = await self._load_cvm_cache()
        return cache.get(cnpj)

    async def _load_cvm_cache(self) -> dict[str, str]:
        if self._cvm_cache is not None:
            return self._cvm_cache
        async with self._cvm_lock:
            if self._cvm_cache is not None:
                return self._cvm_cache
            try:
                async with build_http_client(timeout=30.0) as client:
                    resp = await get_with_retry(client, self.CVM_CADASTRO_URL)
                    resp.raise_for_status()
                    raw = resp.content
            except httpx.HTTPError:
                self._cvm_cache = {}
                return self._cvm_cache

            # CVM cadastro CSV is published in Latin-1 with ';' delimiters.
            try:
                text = raw.decode("latin-1")
            except UnicodeDecodeError:
                self._cvm_cache = {}
                return self._cvm_cache

            mapping: dict[str, str] = {}
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            for row in reader:
                raw_cnpj = row.get("CNPJ_CIA") or ""
                code = row.get("CD_CVM") or ""
                cleaned = _DIGITS_RE.sub("", raw_cnpj)
                if len(cleaned) == 14 and code:
                    mapping[cleaned] = code.strip()
            self._cvm_cache = mapping
            return self._cvm_cache


def _match_from_dadosbrasil(item: dict[str, Any]) -> CompanyMatch | None:
    if not isinstance(item, dict):
        return None
    tax_id = _DIGITS_RE.sub("", str(item.get("tax_id") or ""))
    if len(tax_id) != 14:
        return None
    name = (item.get("legal_name") or item.get("trade_name") or "").strip()
    if not name:
        return None
    uf = (item.get("uf") or "").strip() or None
    return CompanyMatch(
        id=tax_id,
        name=name,
        country="BR",
        identifiers=[
            RegistryIdentifier(type=IdentifierType.VAT, value=tax_id, label="CNPJ"),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=tax_id, label="CNPJ"
            ),
        ],
        address=uf,
        status=(item.get("registration_status") or "").strip() or None,
        source_url=f"https://api.dadosbrasil.net/api/v1/companies/{tax_id}",
    )


def _read_dfp_rows(zf: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    if member not in zf.namelist():
        return []
    text = zf.read(member).decode("latin-1")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def _find_dfp_index_row(
    zf: zipfile.ZipFile, member: str, cnpj: str
) -> dict[str, str] | None:
    for row in _read_dfp_rows(zf, member):
        if _DIGITS_RE.sub("", row.get("CNPJ_CIA") or "") == cnpj:
            return row
    return None


def _parse_dfp_statements(
    zf: zipfile.ZipFile, year: int, cnpj: str, scope: str
) -> dict[str, Any]:
    balance_sheet: dict[str, float] = {}
    income_statement: dict[str, float] = {}
    members = (
        (f"dfp_cia_aberta_BPA_{scope}_{year}.csv", _BPA_ACCOUNTS, balance_sheet),
        (f"dfp_cia_aberta_BPP_{scope}_{year}.csv", _BPP_ACCOUNTS, balance_sheet),
        (f"dfp_cia_aberta_DRE_{scope}_{year}.csv", _DRE_ACCOUNTS, income_statement),
    )
    for member, accounts, target in members:
        for row in _read_dfp_rows(zf, member):
            if row.get("ORDEM_EXERC") != "ÚLTIMO":
                continue
            if _DIGITS_RE.sub("", row.get("CNPJ_CIA") or "") != cnpj:
                continue
            key = accounts.get((row.get("CD_CONTA") or "").strip())
            if key is None:
                continue
            value = _scaled_value(row.get("VL_CONTA"), row.get("ESCALA_MOEDA"))
            if value is not None:
                target[key] = value

    if {"current_liabilities", "non_current_liabilities"} <= balance_sheet.keys():
        balance_sheet["total_liabilities"] = (
            balance_sheet["current_liabilities"]
            + balance_sheet["non_current_liabilities"]
        )

    out: dict[str, Any] = {}
    if balance_sheet:
        out["balance_sheet"] = balance_sheet
    if income_statement:
        out["income_statement"] = income_statement
    return out


def _scaled_value(raw: Any, scale: Any) -> float | None:
    value = _coerce_float(raw)
    if value is None:
        return None
    if str(scale or "").strip().upper().startswith("MIL"):
        value *= 1000
    return value


def _details_from_payload(cnpj: str, data: dict[str, Any]) -> CompanyDetails:
    name = (data.get("razao_social") or data.get("nome") or "").strip()
    trade_name = (data.get("nome_fantasia") or "").strip() or None

    inc_date = _parse_date(
        data.get("data_inicio_atividade") or data.get("abertura")
    )
    status_value = data.get("descricao_situacao_cadastral") or data.get("situacao")
    legal_form = data.get("descricao_natureza_juridica") or data.get("natureza_juridica")

    cnae_primary = (
        str(data.get("cnae_fiscal"))
        if data.get("cnae_fiscal") is not None
        else None
    )
    cnae_codes: list[str] = []
    if cnae_primary:
        cnae_codes.append(cnae_primary)
    for sec in data.get("cnaes_secundarios") or []:
        code = sec.get("codigo") if isinstance(sec, dict) else None
        if code is not None:
            cnae_codes.append(str(code))

    phone = _compose_phone(
        data.get("ddd_telefone_1"),
        data.get("ddd_telefone_2"),
        data.get("telefone"),
    )
    email = (data.get("email") or "").strip().lower() or None
    capital = _coerce_float(data.get("capital_social"))

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.VAT, value=cnpj, label="CNPJ"
        ),
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=cnpj, label="CNPJ"
        ),
    ]

    raw_extra: dict[str, Any] = dict(data)
    if trade_name:
        raw_extra["trade_name"] = trade_name

    return CompanyDetails(
        id=cnpj,
        name=name or trade_name or cnpj,
        country="BR",
        legal_form=legal_form,
        status=status_value,
        incorporation_date=inc_date,
        registered_address=_compose_address(data),
        capital_amount=capital,
        capital_currency="BRL" if capital is not None else None,
        nace_codes=cnae_codes,
        identifiers=identifiers,
        directors=_directors_from_qsa(data.get("qsa") or []),
        phone=phone,
        email=email,
        raw=raw_extra,
        source_url=f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
    )


def _directors_from_qsa(qsa: list[Any]) -> list[Director]:
    directors: list[Director] = []
    for entry in qsa:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("nome_socio") or entry.get("nome") or "").strip()
        if not name:
            continue
        role = (
            entry.get("qualificacao_socio")
            or entry.get("qual")
            or entry.get("codigo_qualificacao_socio")
        )
        directors.append(
            Director(
                name=name,
                role=str(role) if role is not None else None,
                appointed_on=_parse_date(entry.get("data_entrada_sociedade")),
            )
        )
    return directors


def _compose_address(data: dict[str, Any]) -> str | None:
    parts = [
        _join_street(data.get("descricao_tipo_de_logradouro"), data.get("logradouro")),
        data.get("numero"),
        data.get("complemento"),
        data.get("bairro"),
        data.get("municipio"),
        data.get("uf"),
        _format_cep(data.get("cep")),
    ]
    cleaned = [str(p).strip() for p in parts if p]
    return ", ".join(cleaned) if cleaned else None


def _join_street(prefix: Any, street: Any) -> str | None:
    s = " ".join(str(p).strip() for p in (prefix, street) if p)
    return s or None


def _format_cep(cep: Any) -> str | None:
    if not cep:
        return None
    digits = _DIGITS_RE.sub("", str(cep))
    if len(digits) != 8:
        return str(cep)
    return f"{digits[:5]}-{digits[5:]}"


def _compose_phone(*candidates: Any) -> str | None:
    for c in candidates:
        if c:
            return str(c).strip()
    return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _receitaws_to_brasilapi_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Map ReceitaWS response to the BrasilAPI field names used downstream."""
    atividade_principal = payload.get("atividade_principal") or []
    atividades_sec = payload.get("atividades_secundarias") or []
    cnae_primary = None
    if atividade_principal:
        code = (atividade_principal[0] or {}).get("code")
        if code:
            cnae_primary = _DIGITS_RE.sub("", code) or None

    secundarios = []
    for a in atividades_sec:
        code = (a or {}).get("code")
        if code:
            secundarios.append({"codigo": _DIGITS_RE.sub("", code)})

    qsa_in = payload.get("qsa") or []
    qsa_out = []
    for q in qsa_in:
        if not isinstance(q, dict):
            continue
        qsa_out.append(
            {
                "nome_socio": q.get("nome"),
                "qualificacao_socio": q.get("qual"),
            }
        )

    return {
        "razao_social": payload.get("nome"),
        "nome_fantasia": payload.get("fantasia"),
        "data_inicio_atividade": payload.get("abertura"),
        "descricao_situacao_cadastral": payload.get("situacao"),
        "descricao_natureza_juridica": payload.get("natureza_juridica"),
        "cnae_fiscal": cnae_primary,
        "cnaes_secundarios": secundarios,
        "ddd_telefone_1": payload.get("telefone"),
        "email": payload.get("email"),
        "logradouro": payload.get("logradouro"),
        "numero": payload.get("numero"),
        "complemento": payload.get("complemento"),
        "bairro": payload.get("bairro"),
        "municipio": payload.get("municipio"),
        "uf": payload.get("uf"),
        "cep": payload.get("cep"),
        "capital_social": payload.get("capital_social"),
        "qsa": qsa_out,
        "_source": "receitaws",
    }
