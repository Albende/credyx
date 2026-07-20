# Costa Rica — GLEIF + Ministerio de Hacienda ATV + listed-issuer disclosures

## Identifier

- Type: `VAT` (primary, since the cédula jurídica doubles as the
  Hacienda-issued corporate tax ID) with `COMPANY_NUMBER` as an alias.
- Format: **Cédula Jurídica** — 10 digits, conventionally displayed as
  `X-XXX-XXXXXX` (e.g. `3-101-000784`).
- Class codes (positions 2..4 of a `3-XXX-...` cédula) encode the legal
  form:
  - `101` — Sociedad Anónima
  - `102` — Sociedad de Responsabilidad Limitada
  - `103` — Sociedad en Nombre Colectivo
  - `104` — Sociedad en Comandita
  - `105` — Empresa Individual de Responsabilidad Limitada
  - `106` — Sucursal de Sociedad Extranjera
  - `107` — Sociedad Cooperativa
  - `108` — Sociedad Civil
  - `109` — Sociedad Extranjera
  - `110` — Asociación Civil
- Pre-1990 state entities (ICE, BNCR, AyA, INS, RECOPE, ...) carry
  `4-000-XXXXXX` cédulas — historically `cédulas físicas
  institucionales`. Both GLEIF and Hacienda's ATV endpoint resolve both
  forms, so the adapter accepts either.
- No check digit. Validation is purely structural (length + leading
  pattern); the upstream source is authoritative for whether a number is
  in use.

## Sources

- **GLEIF — Global LEI index** (`https://api.gleif.org/api/v1`)
  - Public, free, no auth. JSON:API. Reachable from anywhere.
  - The only free machine-readable source that exposes CR entities **by
    name**. Every CR record carries `entity.registeredAs` = the cédula
    jurídica, so GLEIF backs both name search (`filter[entity.legalName]`,
    substring match, constrained to `filter[entity.legalAddress.country]=CR`)
    and cédula lookup (`filter[entity.registeredAs]=X-XXX-XXXXXX`).
  - Coverage: the ~280 CR entities that hold an LEI — banks, BNV-listed
    issuers, large exporters, investment funds, state institutions.
- **Ministerio de Hacienda — Consulta Situación Tributaria (ATV)**
  - `GET https://api.hacienda.go.cr/fe/ae?identificacion={cedula}` (no auth,
    free) returns registered name, legal-form class, current tax status
    (`Activo` / `Moroso` / `No inscrito`) and CAEC activity codes for **every**
    taxpayer.
  - **Geoblocked as of 2026**: requests from non-CR IPs receive an HTML
    "acceso restringido" page instead of JSON (FlareSolverr does not help — it
    is geographic, not a JS/Cloudflare wall). The adapter still tries Hacienda
    first (richest, widest-coverage record where it runs on a CR-reachable
    network) and falls back to GLEIF when the geoblock/non-JSON body appears.
  - Rate limit: undocumented; self-throttled at 30 req/min.
- **Listed-issuer financial statements**
  - Costa Rica's official disclosure registry (SUGEVAL RNVI,
    `aplicaciones.sugeval.fi.cr`) resets TLS connections from non-CR IPs, so
    financials come from listed issuers' own published audited/consolidated
    statements.
  - `_LISTED_FINANCIALS` maps a listed cédula → its public
    financial-statements index. `fetch_financials` scrapes that index **live**
    on every call and returns one `FinancialFiling` per real, downloadable
    year-end/audited PDF (`document_url` is verified to serve `%PDF` bytes
    before it is surfaced). Non-listed companies get `[]` — never a fabricated
    filing.
  - Seeded issuer: **Florida Ice and Farm Company (FIFCO)** `3-101-000784`
    → `https://www.fifco.com/en/financial-statements/` (audited consolidated
    statements, colones).

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | Live — GLEIF (`legalName` substring, CR-scoped) |
| Lookup by Cédula Jurídica (`VAT` / `COMPANY_NUMBER`) | Live — Hacienda ATV where reachable, else GLEIF `registeredAs` |
| Financials | Live for listed issuers with public filed PDFs (real downloadable annual statements); `[]` otherwise |

## Test companies (real)

- **Florida Ice and Farm Company (FIFCO)** — `3-101-000784` — BNV's flagship
  listed issuer. Covers all three capabilities: GLEIF name search + cédula
  lookup, and live audited-statement PDFs from fifco.com.
- **Instituto Costarricense de Electricidad (ICE)** — `4-000-042139` —
  state-owned electricity/telecoms; pre-1990 state-entity cédula. In GLEIF.
- **Banco Nacional de Costa Rica** — `4-000-001021` — state-owned bank. In GLEIF.
- **Banco LAFISE S.A.** — `3-101-023155` — private bank; GLEIF cédula lookup.

## Status

Live for name search and cédula lookup via GLEIF (with Hacienda ATV as the
richer path where the network can reach it). Financials are live for
BNV-listed issuers whose audited statements are published as downloadable
PDFs (FIFCO today), scraped fresh each call with the document link verified to
download; every other company returns `[]`. No mock data anywhere.

## Phase-2 follow-ups

1. **SUGEVAL RNVI proxy**: `aplicaciones.sugeval.fi.cr` is the official
   per-emisor estados-financieros registry but resets non-CR IPs at the TLS
   layer. Once a CR-egress proxy or the browser pool with a CR exit is wired
   up, replace the per-issuer `_LISTED_FINANCIALS` seed with a live RNVI scrape
   covering every registered issuer.
2. **Hacienda ATV from CR egress**: routing the ATV call through a CR-resident
   proxy restores full-taxpayer lookup coverage (name, tax status, CAEC codes)
   beyond the ~280 LEI-registered entities GLEIF sees.
3. **PDF extraction**: once the PDF pipeline lands, parse the FIFCO/issuer
   audited PDFs into `FinancialFiling.structured_data` (balance sheet + P&L in
   colones) instead of only surfacing the document link.
4. **CAEC → NACE mapping**: Hacienda's `actividades` codes follow the CAEC
   classification; cross-map to NACE Rev. 2 for the industry benchmarks table.
5. **Sanctions/PEP**: wire `OpenSanctionsClient` to screen CR principals —
   several regional designations flow through CR shell companies.
