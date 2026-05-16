"""Brazil adapter — BrasilAPI (Receita Federal CNPJ mirror) with ReceitaWS fallback.

Sources:
- Primary: https://brasilapi.com.br/api/cnpj/v1/{cnpj} — free, no auth, ~3 req/s.
- Fallback: https://www.receitaws.com.br/v1/cnpj/{cnpj} — free tier 3 req/min.
- Listed-company financials: CVM cadastro CSV
  http://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv —
  maps CNPJ to CVM code, used to construct rad.cvm.gov.br DFP links.

Identifier: CNPJ (14 digits, format XX.XXX.XXX/XXXX-XX). CNPJ doubles as
the Brazilian corporate tax ID; there is no separate VAT number, so we
expose it as the primary VAT and also accept COMPANY_NUMBER.

Name search is not available: Receita Federal's public consultation
requires solving a CAPTCHA and is therefore raised as
`AdapterNotImplementedError` per the project's no-mock-data rule.
"""
from __future__ import annotations

import asyncio
import csv
import io
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
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_DIGITS_RE = re.compile(r"\D+")
_CNPJ_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_WEIGHTS_2 = [6] + _CNPJ_WEIGHTS_1


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
    CVM_CADASTRO_URL = (
        "http://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    )

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
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search blocked by CAPTCHA at Receita Federal. "
                "Financials limited to CVM-listed companies."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Brazilian Receita Federal does not expose free name search "
            "(public lookup requires CAPTCHA). Use CNPJ lookup directly."
        )

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
        cvm_code = await self._cvm_code_for(cnpj)
        if cvm_code is None:
            return []
        # CVM does not expose direct per-year DFP URLs without a session. The
        # rad.cvm.gov.br landing page lists every annual report (DFP) and
        # interim filing for the company. Surface that as the document URL —
        # the consumer can drill into specific years.
        rad_url = (
            "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx"
            f"?codigoCVM={cvm_code}"
        )
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=cnpj,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="BRL",
                    structured_data=None,
                    document_url=rad_url,
                    document_format="html",
                    source_url=rad_url,
                )
            )
        return filings

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
