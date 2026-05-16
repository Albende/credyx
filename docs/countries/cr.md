# Costa Rica — Ministerio de Hacienda ATV + BNV

## Identifier

- Type: `VAT` (primary, since the cédula jurídica doubles as the
  Hacienda-issued corporate tax ID) with `COMPANY_NUMBER` as an alias.
- Format: **Cédula Jurídica** — 10 digits, conventionally displayed as
  `X-XXX-XXXXXX` (e.g. `3-101-005514`).
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
  institucionales`. Hacienda's ATV endpoint resolves both forms via the
  same query, so the adapter accepts either.
- No check digit. Validation is purely structural (length + leading
  pattern); Hacienda is the source of truth for whether a number is in
  use.

## Sources

- **Ministerio de Hacienda — Consulta Situación Tributaria (ATV)**
  - Public portal: `https://www.hacienda.go.cr/ATV/ConsultaSituacionTributaria.aspx`
  - JSON endpoint used by the adapter:
    `GET https://api.hacienda.go.cr/fe/ae?identificacion={cedula}`
  - Auth: none. Cost: free. Same endpoint that backs Costa Rica's
    electronic-invoicing ("factura electrónica") integrations.
  - Returns: registered name, legal-form class, current tax status
    (`Activo` / `Moroso` / `No inscrito`), and any active CAEC economic
    activity codes.
  - Rate limit: undocumented; we self-throttle at 30 req/min.
- **Registro Nacional — Personas Jurídicas (RNP)**
  - `https://www.rnpdigital.com/` and `https://www.registronacional.go.cr/`
  - Gated behind a session login for any query. No free name-search
    API. Per the no-mock-data rule the adapter raises
    `AdapterNotImplementedError` from `search_by_name` rather than
    scrape behind the portal session.
- **Bolsa Nacional de Valores (BNV)**
  - `https://www.bolsacr.com/` — limited free disclosure index for
    listed emisores. No per-cédula REST feed today; we surface the
    `/emisores` landing page as a discovery pointer for the small set
    of known listed cédulas and return `[]` for everything else.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | Blocked — RNP requires session login, Hacienda is identifier-only |
| Lookup by Cédula Jurídica (`VAT` / `COMPANY_NUMBER`) | Live — Hacienda ATV |
| Financials | Limited — BNV index URL for known listed emisores; `[]` otherwise |

## Test companies (real)

- **Instituto Costarricense de Electricidad (ICE)** — `4-000-042139` —
  state-owned electricity and telecoms; pre-1990 state-entity cédula.
- **Florida Bebidas S.A.** (Coca-Cola CR / FIFCO bottler) —
  `3-101-005514` — listed on the BNV.
- **Banco Nacional de Costa Rica** — `4-000-001021` — state-owned bank.
- **DEMASA (Distribuidora Madisa S.A.)** — `3-101-010300` —
  consumer-goods distributor.

## Status

Live for cédula lookup via Hacienda ATV. Financials limited to a small
allow-list of BNV-listed emisores (returns the disclosure index URL,
not parsed line items). Name search is intentionally not implemented —
no free public source exposes it.

## Phase-2 follow-ups

1. **BNV per-emisor scrape**: once the Playwright pool
   (`packages/adapters/_base/browser.py`) is wired up, replace the
   static `_BNV_LISTED` allow-list with a directory scrape of
   `bolsacr.com/emisores` so every BNV-listed cédula is detected
   dynamically.
2. **SUGEF supervised-entity feed**: the Superintendencia General de
   Entidades Financieras publishes balance-sheet packets for banks,
   financieras and mutuales (BNCR, BCR, Popular, BAC San José, ...).
   PDF-only today; once the PDF extraction pipeline (roadmap item 1)
   lands they become structured `FinancialFiling.structured_data`.
3. **RNP digital-records portal**: `rnpdigital.com` exposes per-cédula
   constitution date, registered domicile, and current directors once
   logged in. A nightly authenticated job would close the gaps left by
   Hacienda ATV (which returns only name + tax status).
4. **CAEC enrichment**: Hacienda's `actividades` codes follow the
   Clasificación de Actividades Económicas Costarricense, a local
   variant of ISIC Rev. 4. Cross-map to NACE Rev. 2 for the industry
   benchmarks table.
5. **Sanctions/PEP**: wire `OpenSanctionsClient` to screen every Costa
   Rican principal. CR is in the OFAC/EU non-target band but several
   regional designations (Nicaragua, Venezuela) flow through CR
   shell-companies — high credit signal.
