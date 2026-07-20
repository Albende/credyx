"""Argentina adapter — CNV (Comisión Nacional de Valores) issuer registry.

AFIP's free ``sr-padron`` REST endpoint was retired; the surviving free padron
service (``ws_sr_constancia_inscripcion``) is SOAP behind a digital certificate,
so it is out of scope for the key-free MVP.

CNV's public "Empresas" site is the free source that ties a CUIT to issuer
identity, name search, and filed financial statements (estados contables) for
every company in the public-offering regime (oferta pública) — YPF, the banks,
the large negotiable-obligations issuers, etc. Companies outside that regime
(e.g. NASDAQ-only names) do not resolve.

Sources — all free, no key:
- Name search: ``GET /SitioWeb/Empresas/AutoComplete?term=`` → JSON list of
  ``{id, cuit, descripcion}``.
- Issuer page: ``GET /SitioWeb/Empresas/Empresa/{cuit}`` — server-rendered
  identity header (razón social, régimen) plus document accordions. Filtered to
  ``formType=INFOFI`` (Información Financiera) it lists each estados-contables
  filing with its balance close date, accounting norm and balance type, each
  linked to the filing on CNV's AIF (``aif2.cnv.gov.ar/presentations/publicview``).

Identifier: CUIT — 11 digits, XX-XXXXXXXX-X, mod-11 checksum on the leading 10.
"""
from __future__ import annotations

import re
from datetime import date

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

_CUIT_DIGITS_RE = re.compile(r"^\d{11}$")
# Mod-11 weights applied to the first 10 digits of the CUIT.
_CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

_HEADER_RE = re.compile(
    r'title-resultados">Resultados de b[^<]*</h2>\s*<h1>\s*(?P<name>.*?)<small>(?P<small>.*?)</small>',
    re.S,
)
_STRONG_RE = re.compile(r"<strong>([^<]+)</strong>")
_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_FECHA_CIERRE_RE = re.compile(r"FECHA CIERRE:\s*(\d{4})-(\d{2})-(\d{2})")
_TIPO_BALANCE_RE = re.compile(r"TIPO BALANCE:\s*([A-Za-zÁÉÍÓÚÑ]+)")
_NORMA_RE = re.compile(r"NORMA CONTABLE:\s*([A-Za-zÁÉÍÓÚÑ ]+?)\s*-")
_PUBLICVIEW_RE = re.compile(
    r'href="(https://aif2\.cnv\.gov\.ar/presentations/publicview/[a-f0-9\-]+)"'
)


def _normalize_cuit(value: str) -> str:
    cleaned = re.sub(r"[\s\-\.]", "", value or "")
    if not _CUIT_DIGITS_RE.match(cleaned):
        raise InvalidIdentifierError(f"CUIT must be 11 digits: {value}")
    total = sum(int(d) * w for d, w in zip(cleaned[:10], _CUIT_WEIGHTS))
    remainder = total % 11
    check = 0 if remainder == 0 else 11 - remainder
    if check == 10 or check != int(cleaned[10]):
        raise InvalidIdentifierError(f"CUIT checksum invalid: {value}")
    return cleaned


def _format_cuit(cuit: str) -> str:
    return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"


class ARAdapter(CountryAdapter):
    country_code = "AR"
    country_name = "Argentina"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    CNV_BASE = "https://www.cnv.gov.ar/SitioWeb"
    # How far back the issuer page is filtered when listing financial filings.
    _FILINGS_LOOKBACK_YEARS = 8

    def _issuer_url(self, cuit: str) -> str:
        return f"{self.CNV_BASE}/Empresas/Empresa/{cuit}"

    async def _fetch_issuer_html(self, cuit: str) -> str:
        fdesde = f"1/1/{date.today().year - self._FILINGS_LOOKBACK_YEARS}"
        async with build_http_client(base_url=self.CNV_BASE) as client:
            resp = await get_with_retry(
                client,
                f"/Empresas/Empresa/{cuit}",
                params={"formType": "INFOFI", "fdesde": fdesde},
            )
            resp.raise_for_status()
            # CNV mislabels these pages as UTF-8 while serving ISO-8859-1 bytes.
            return resp.content.decode("latin-1")

    async def health_check(self) -> AdapterHealth:
        capabilities = {"search": True, "lookup": True, "financials": True}
        try:
            async with build_http_client(base_url=self.CNV_BASE) as client:
                resp = await get_with_retry(
                    client, "/Empresas/AutoComplete", params={"term": "YPF"}
                )
                resp.raise_for_status()
                hits = resp.json()
            if not isinstance(hits, list) or not hits:
                raise ValueError("CNV AutoComplete returned no results for probe term")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities=capabilities,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities=capabilities,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "CNV public issuer registry: name search, CUIT lookup and estados "
                "contables for oferta-pública companies. Non-issuers do not resolve."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        term = (name or "").strip()
        if len(term) < 3:
            raise InvalidIdentifierError(
                "CNV name search requires at least 3 characters"
            )
        async with build_http_client(base_url=self.CNV_BASE) as client:
            resp = await get_with_retry(
                client, "/Empresas/AutoComplete", params={"term": term}
            )
            resp.raise_for_status()
            try:
                rows = resp.json()
            except ValueError:
                return []

        matches: list[CompanyMatch] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            desc = (row.get("descripcion") or "").strip()
            if not desc:
                continue
            try:
                cuit = _normalize_cuit(str(row.get("cuit") or ""))
            except InvalidIdentifierError:
                continue
            matches.append(
                CompanyMatch(
                    id=cuit,
                    name=desc,
                    country="AR",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.VAT, value=cuit, label="CUIT"
                        )
                    ],
                    source_url=self._issuer_url(cuit),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"AR only supports VAT (CUIT) / COMPANY_NUMBER, got {id_type}"
            )
        cuit = _normalize_cuit(value)
        html = await self._fetch_issuer_html(cuit)
        if "CUIT:</strong>" not in html or _format_cuit(cuit) not in html:
            return None
        header = _HEADER_RE.search(html)
        if header is None:
            return None
        name = _TAG_RE.sub("", header.group("name")).strip()
        if not name:
            return None
        regime_match = _STRONG_RE.search(header.group("small"))
        status = regime_match.group(1).strip() if regime_match else None

        return CompanyDetails(
            id=cuit,
            name=name,
            country="AR",
            status=status,
            capital_currency="ARS",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=cuit, label="CUIT"),
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=cuit, label="CUIT"
                ),
            ],
            raw={"regime": status, "source": "CNV"},
            source_url=self._issuer_url(cuit),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cuit = _normalize_cuit(company_id)
        html = await self._fetch_issuer_html(cuit)
        if "CUIT:</strong>" not in html or _format_cuit(cuit) not in html:
            return []

        best_per_year: dict[int, _Statement] = {}
        for row_html in _ROW_RE.findall(html):
            statement = _parse_statement_row(row_html)
            if statement is None:
                continue
            current = best_per_year.get(statement.period_end.year)
            if current is None or statement.beats(current):
                best_per_year[statement.period_end.year] = statement

        selected = sorted(
            best_per_year.values(), key=lambda s: s.period_end, reverse=True
        )[:years]

        return [
            FinancialFiling(
                company_id=cuit,
                year=s.period_end.year,
                type=(
                    FilingType.ANNUAL_REPORT
                    if s.period_end.month == 12
                    else FilingType.BALANCE_SHEET
                ),
                period_end=s.period_end,
                currency="ARS",
                structured_data={
                    "tipo_balance": s.tipo_balance,
                    "norma_contable": s.norma,
                },
                document_url=s.document_url,
                document_format="html",
                source_url=self._issuer_url(cuit),
            )
            for s in selected
        ]


class _Statement:
    __slots__ = ("period_end", "tipo_balance", "norma", "document_url")

    def __init__(
        self, period_end: date, tipo_balance: str, norma: str, document_url: str
    ) -> None:
        self.period_end = period_end
        self.tipo_balance = tipo_balance
        self.norma = norma
        self.document_url = document_url

    def beats(self, other: _Statement) -> bool:
        if self.period_end != other.period_end:
            return self.period_end > other.period_end
        return (
            self.tipo_balance == "CONSOLIDADO"
            and other.tipo_balance != "CONSOLIDADO"
        )


def _parse_statement_row(row_html: str) -> _Statement | None:
    cells = _CELL_RE.findall(row_html)
    if len(cells) < 4:
        return None
    desc = _TAG_RE.sub(" ", cells[2]).upper()
    if "NORMA CONTABLE:" not in desc or "ESTADOS CONTABLES" not in desc:
        return None
    # "OTROS IDIOMAS" rows are foreign-language / foreign-currency duplicates of
    # the primary ARS statement — skip them to avoid double-counting a year.
    if "OTROS IDIOMAS" in desc:
        return None
    fecha = _FECHA_CIERRE_RE.search(desc)
    url = _PUBLICVIEW_RE.search(row_html)
    if fecha is None or url is None:
        return None
    period_end = date(int(fecha.group(1)), int(fecha.group(2)), int(fecha.group(3)))
    tipo = _TIPO_BALANCE_RE.search(desc)
    norma = _NORMA_RE.search(desc)
    return _Statement(
        period_end=period_end,
        tipo_balance=tipo.group(1) if tipo else "",
        norma=norma.group(1).strip() if norma else "",
        document_url=url.group(1),
    )
