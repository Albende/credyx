"""Bolivia adapter — SEPREC Directorio Empresarial (public REST API).

SEPREC (Servicio Plurinacional de Registro de Comercio) backs its public
"Directorio Empresarial" web app (``miempresa.seprec.gob.bo``) with an
unauthenticated JSON API at ``https://servicios.seprec.gob.bo/api``. Three
endpoints are public and key-free:

- ``empresas/buscarEmpresas`` — full-text search by ``nombre`` (razón social)
  or ``matricula``.
- ``empresas/informacionBasicaEmpresa/{id}/establecimiento/{est}`` — the full
  public registry record: NIT, legal form, registered address, contacts,
  objeto social, fiscal-close month and last renewed gestión.
- ``empresas/consultarEstadoHabilitacion/{matricula}`` — habilitation state.

In the unified SEPREC system the Matrícula de Comercio and the NIT are the same
number, so ``VAT`` and ``COMPANY_NUMBER`` resolve through the same matrícula
search.

The filed financial statements themselves (line items, audited PDFs) sit behind
the owner-login portal, so ``fetch_financials`` returns the annual-renewal
filing index derived from the company's live registry record — the gestiones a
company in ``MATRICULA RENOVADA`` status filed to keep its matrícula current
(annual filing of the balance sheet is mandatory under the Código de Comercio),
dated by its declared fiscal-close month. It never emits fabricated numbers and
never a document URL it cannot download.

Identifiers:
- NIT / Matrícula de Comercio — a single number, exposed as both ``VAT``
  (primary) and ``COMPANY_NUMBER``.
"""
from __future__ import annotations

import calendar
from datetime import date
from urllib.parse import quote

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


class BOAdapter(CountryAdapter):
    country_code = "BO"
    country_name = "Bolivia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    API_BASE = "https://servicios.seprec.gob.bo/api"
    PORTAL = "https://miempresa.seprec.gob.bo"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.API_BASE, timeout=20.0) as client:
                resp = await get_with_retry(
                    client,
                    "/empresas/buscarEmpresas",
                    params={"filtro": "BANCO", "tipoFiltro": "nombre", "limite": 1, "pagina": 1},
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"SEPREC API unreachable: {str(exc)[:180]}",
            )
        ok = resp.status_code == 200 and (resp.json().get("finalizado") is True)
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                None
                if ok
                else f"SEPREC buscarEmpresas returned HTTP {resp.status_code}"
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = (name or "").strip()
        if not query:
            return []
        async with build_http_client(base_url=self.API_BASE, timeout=25.0) as client:
            rows = await self._buscar(client, query, "nombre", limit)
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            matricula = str(row.get("matricula") or "").strip()
            if not matricula:
                continue
            matches.append(self._row_to_match(row, matricula))
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"BO supports VAT (NIT) and COMPANY_NUMBER (Matrícula), got {id_type}"
            )
        matricula = (value or "").strip()
        if not matricula:
            return None
        async with build_http_client(base_url=self.API_BASE, timeout=25.0) as client:
            row = await self._find_by_matricula(client, matricula)
            if row is None:
                return None
            basic = await self._fetch_basic(client, row["id"], row["idEstablecimiento"])
        if basic is None:
            return None
        return self._basic_to_details(basic, row["id"], row["idEstablecimiento"])

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        matricula = (company_id or "").strip()
        if not matricula:
            return []
        async with build_http_client(base_url=self.API_BASE, timeout=25.0) as client:
            row = await self._find_by_matricula(client, matricula)
            if row is None:
                return []
            basic = await self._fetch_basic(client, row["id"], row["idEstablecimiento"])
        if basic is None:
            return []
        last_year = basic.get("ultimoAnioActualizacion")
        if not isinstance(last_year, int) or last_year <= 0:
            return []
        nit = str(basic.get("nit") or matricula).strip()
        month = self._closing_month(basic.get("mesCierreGestion"))
        renovada = "RENOVADA" in (
            (basic.get("codEstadoActualizacion") or {}).get("nombre") or ""
        ).upper()
        active = (basic.get("estado") or "").upper() == "ACTIVO"
        source_url = (
            f"{self.API_BASE}/empresas/informacionBasicaEmpresa/"
            f"{row['id']}/establecimiento/{row['idEstablecimiento']}"
        )
        span = max(1, years) if (renovada and active) else 1
        filings: list[FinancialFiling] = []
        for offset in range(span):
            yr = last_year - offset
            filings.append(
                FinancialFiling(
                    company_id=nit,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=self._period_end(yr, month),
                    currency="BOB",
                    structured_data=None,
                    document_url=None,
                    document_format=None,
                    source_url=source_url,
                )
            )
        return filings

    async def _buscar(
        self, client: httpx.AsyncClient, filtro: str, tipo: str, limit: int
    ) -> list[dict]:
        resp = await get_with_retry(
            client,
            "/empresas/buscarEmpresas",
            params={"filtro": filtro, "tipoFiltro": tipo, "limite": limit, "pagina": 1},
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("finalizado"):
            return []
        return (payload.get("datos") or {}).get("filas") or []

    async def _find_by_matricula(
        self, client: httpx.AsyncClient, matricula: str
    ) -> dict | None:
        rows = await self._buscar(client, matricula, "matricula", 5)
        for row in rows:
            if str(row.get("matricula") or "").strip() == matricula and row.get(
                "idEstablecimiento"
            ):
                return row
        for row in rows:
            if row.get("idEstablecimiento") and row.get("id"):
                return row
        return None

    async def _fetch_basic(
        self, client: httpx.AsyncClient, company_id: str, establecimiento: str
    ) -> dict | None:
        resp = await get_with_retry(
            client,
            f"/empresas/informacionBasicaEmpresa/{company_id}/establecimiento/{establecimiento}",
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("finalizado"):
            return None
        return payload.get("datos")

    def _row_to_match(self, row: dict, matricula: str) -> CompanyMatch:
        depto = ((row.get("direccion") or {}).get("codDepartamento") or {}).get("nombre")
        return CompanyMatch(
            id=matricula,
            name=self._clean(row.get("razonSocial")),
            country=self.country_code,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=matricula, label="NIT / Matrícula"
                )
            ],
            address=self._clean(depto) or None,
            status=row.get("estado"),
            source_url=(
                f"{self.API_BASE}/empresas/buscarEmpresas"
                f"?filtro={quote(matricula)}&tipoFiltro=matricula&limite=5&pagina=1"
            ),
        )

    def _basic_to_details(
        self, d: dict, company_id: str, establecimiento: str
    ) -> CompanyDetails:
        matricula = str(d.get("matricula") or "").strip()
        nit = str(d.get("nit") or matricula).strip()
        identifiers = [RegistryIdentifier(type=IdentifierType.VAT, value=nit, label="NIT")]
        if matricula:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=matricula,
                    label="Matrícula de Comercio",
                )
            )
        phone, email = self._extract_contacts(d.get("contactos") or [])
        return CompanyDetails(
            id=matricula or nit,
            name=self._clean(d.get("razonSocial")),
            country=self.country_code,
            legal_form=(d.get("codTipoUnidadEconomica") or {}).get("nombre"),
            status=d.get("estado"),
            registered_address=self._format_address(d.get("direccion") or {}),
            capital_currency="BOB",
            identifiers=identifiers,
            phone=phone,
            email=email,
            raw=d,
            source_url=(
                f"{self.API_BASE}/empresas/informacionBasicaEmpresa/"
                f"{company_id}/establecimiento/{establecimiento}"
            ),
        )

    @staticmethod
    def _extract_contacts(contactos: list[dict]) -> tuple[str | None, str | None]:
        phone: str | None = None
        email: str | None = None
        for contacto in contactos:
            tipo = (contacto.get("tipoContacto") or "").upper()
            for item in contacto.get("descripcion") or []:
                if tipo == "TELEFONO" and phone is None and item.get("numero"):
                    phone = str(item["numero"]).strip()
                if tipo == "CORREO" and email is None and item.get("correo"):
                    email = str(item["correo"]).strip()
        return phone, email

    @staticmethod
    def _format_address(direccion: dict) -> str | None:
        parts = [
            direccion.get("nombreVia"),
            direccion.get("numeroDomicilio"),
            direccion.get("edificio"),
            (direccion.get("codMunicipio") or {}).get("nombre"),
            (direccion.get("codDepartamento") or {}).get("nombre"),
        ]
        cleaned = [BOAdapter._clean(part) for part in parts if part]
        address = ", ".join(part for part in cleaned if part)
        return address or None

    @staticmethod
    def _closing_month(raw: object) -> int:
        try:
            month = int(str(raw).strip())
        except (TypeError, ValueError):
            return 12
        return month if 1 <= month <= 12 else 12

    @staticmethod
    def _period_end(year: int, month: int) -> date:
        return date(year, month, calendar.monthrange(year, month)[1])

    @staticmethod
    def _clean(text: str | None) -> str:
        return " ".join((text or "").split())
