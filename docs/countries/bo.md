# 🇧🇴 Bolivia — SEPREC Directorio Empresarial

## Identifiers

- `VAT` → **NIT** (Número de Identificación Tributaria). In the unified SEPREC
  system the NIT and the Matrícula de Comercio are the same number.
- `COMPANY_NUMBER` → **Matrícula de Comercio**, issued by SEPREC. Same value as
  the NIT for entities registered under the current system.

## Sources

- **SEPREC** (Servicio Plurinacional de Registro de Comercio) —
  public "Directorio Empresarial" web app at https://miempresa.seprec.gob.bo/
  backed by an **unauthenticated JSON API** at
  `https://servicios.seprec.gob.bo/api`. Key-free, no CAPTCHA on these routes.
  - `GET /empresas/buscarEmpresas?filtro={q}&tipoFiltro={nombre|matricula}&limite={n}&pagina={p}`
    — company search by razón social (`nombre`) or exact matrícula (`matricula`).
    Any other `tipoFiltro` value is ignored and returns the full base (~408k rows),
    so only `nombre` / `matricula` are used.
  - `GET /empresas/informacionBasicaEmpresa/{id}/establecimiento/{est}` — full
    public record: NIT, razón social, legal form, registered address, phone,
    email, objeto social, `mesCierreGestion` (fiscal-close month) and
    `ultimoAnioActualizacion` (last renewed gestión).
  - `GET /empresas/consultarEstadoHabilitacion/{matricula}` — habilitation state.
- **Login-gated** (owner account only, out of scope for MVP): the detailed
  financial-statement endpoints `empresas/informacionGeneralEmpresa/{id}`,
  `empresas/gestiones-financieras/{id}` and `empresas/informacion-financiera/{id}`
  return `401 Usuario no autorizado` without a SEPREC user session, so filed
  balance-sheet line items are not retrievable key-free.
- **BBV** (Bolsa Boliviana de Valores) — https://www.bbv.com.bo/EEFFEmisores/
  publishes issuer PDFs, but the host is currently unreachable from outside
  Bolivia (connections time out at the network layer, not a bot wall), so it is
  not used by the adapter.

## Auth, rate limits, ToS

- No API key.
- No documented rate limits; adapter throttles itself to 30 req/min.
- The `servicios.seprec.gob.bo/api` routes above are the ones the public
  Directorio Empresarial calls directly and require no session token.

## Capabilities

- `search_by_name` → live, via `buscarEmpresas` (`tipoFiltro=nombre`).
- `lookup_by_identifier` (VAT / COMPANY_NUMBER) → live: matrícula search →
  `informacionBasicaEmpresa`. Returns legal form, status, address, contacts.
- `fetch_financials` → the **annual-renewal filing index** derived from the
  live registry record. A company in `MATRICULA RENOVADA` + `ACTIVO` status must
  file its balance sheet annually to renew its matrícula (Código de Comercio),
  so filings are emitted for the trailing `years` gestiones ending at
  `ultimoAnioActualizacion`, dated by `mesCierreGestion`. Metadata only —
  currency `BOB`, `source_url` pointing at the company-specific registry record,
  `document_url=None`, `structured_data=None`. No fabricated numbers. Non-renewed
  or inactive companies yield only the single last-filed gestión.

## Test companies (real)

- **Banco Mercantil Santa Cruz S.A.** — matrícula/NIT `1020557029`, id 12792.
- **Telefónica Celular de Bolivia (TELECEL / Tigo) S.A.** — matrícula/NIT
  `1020255020`, id 13022.
- **Farmacias Corporativas S.A. (FARMACORP)** — matrícula/NIT `1015447026`.
- **YPFB Andina S.A.** — matrícula/NIT `1028349027`.

## Status

🟢 **Live** — search, lookup and financials all return real data from the SEPREC
public JSON API with no API key. Financials are filing-index metadata (no line
items, since the audited-statement endpoints are login-gated); no mock data is
ever returned.

**Recommended next step:** if a SEPREC service account becomes available,
`empresas/informacion-financiera/{id}` exposes structured line items
(ventas netas, costo de ventas, etc.) that would let `fetch_financials` populate
`structured_data`.
