# 🇨🇴 Colombia — RUES (CONFECAMARAS) + Supersociedades (datos.gov.co)

## Identifier

- Type: `VAT` (primary, since NIT is the DIAN-issued tax + corporate ID)
  with `COMPANY_NUMBER` exposed as an alias.
- Format: **NIT** (Número de Identificación Tributaria). 9 or 10 body
  digits plus one check digit, conventionally displayed as
  `XXX.XXX.XXX-D` (e.g. `899.999.068-1`).
- Check digit: weighted sum mod 11. Weights, applied right-to-left over
  the body only, are `[3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59,
  67, 71]`. If the remainder is 0 or 1 the check is the remainder
  itself; otherwise it is `11 - remainder`.
- The adapter accepts every common rendering: `899.999.068-1`,
  `899999068-1`, `CO 899999068-1`, the bare 9-digit body, or the
  11-digit body+check concatenation. A 10-digit input without a dash
  is treated as a 10-digit body (the dash form is the only unambiguous
  way to attach a check digit to a 9-digit body).

## Sources

- **RUES (Registro Único Empresarial y Social)** — `https://www.rues.org.co/`
  - Operated by **CONFECAMARAS** (Confederación Colombiana de Cámaras
    de Comercio), the umbrella body for the country's chambers of
    commerce.
  - **Auth**: none. **Cost**: free. The modernised (2024→) JSON backend
    replaced the old `/RM/Consultas` form path. Both hosts return a bare
    `403` unless the request carries the portal's browser headers
    (`User-Agent` + `Origin`/`Referer`), which the adapter sends.
  - **Endpoints used**:
    - `POST https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM`
      — advanced search. JSON body `{"nit": "<body>"}` for a direct NIT
      lookup or `{"razon": "<name>"}` for a name search. Returns
      `{"registros": [...], "cant_registros": N, "error": {...}}` where
      each record carries an `id_rm` (register-entry id). Name-search
      records do **not** include the NIT — only `id_rm`.
    - `GET https://ruesapi.rues.org.co/WEB2/api/Expediente/DetalleRM/{id_rm}`
      — the full expediente for one entry (`razon_social`,
      `numero_identificacion` + `dv`, address, CIIU codes, `fecha_matricula`,
      `organizacion_juridica`, `estado`). The adapter resolves each search
      hit through this endpoint to recover the NIT and enrich details.
  - If a response is not JSON or lacks `registros`,
    `AdapterNotImplementedError` is raised — never invent.
  - **Rate limit**: undocumented; we self-throttle at 30 req/min.
- **Supersociedades — NIIF financial statements (open data)** —
  `https://www.datos.gov.co/` (Socrata / SODA API, **no key required**).
  - The Superintendencia de Sociedades publishes the IFRS/NIIF financial
    statements every non-financial company is legally required to file.
    Four datasets, joined by `codigo_instancia` (one filed statement set):
    - `pfdp-zks5` — Estado de Situación Financiera (balance sheet)
    - `prwj-nzxa` — Estado de Resultado Integral (income statement)
    - `ctcp-462n` — Estado de Flujo de Efectivo (cash flow)
    - `y3gh-x5g7` — Otro Resultado Integral (OCI)
  - Long format: `nit`, `fecha_corte`, `concepto`, `periodo` (we take
    `Periodo Actual`), `valor`, `punto_entrada`. The adapter keeps annual
    (Dec-31) filings, prefers **entity-level (non-consolidated)** over
    consolidated statements, maps the filed line items into the unified
    `structured_data` schema (`balance_sheet` / `income_statement` /
    `cash_flow`), and returns one `FinancialFiling` per year. Values are
    in **thousands of COP**. Coverage runs from FY2015 to the latest
    filed year (FY2025 as of writing).
  - **Encoding caveat**: the published data corrupts many accented
    characters to `U+FFFD` inconsistently, so concept labels are matched
    through an ASCII skeleton (`_skeleton`) that drops every non-`[a-z0-9 ]`
    character from both the data and the map keys.
  - **Not covered**: SFC-supervised entities (banks, insurers, listed
    issuers such as Ecopetrol, Bancolombia, Grupo Argos, Avianca) report
    to the **Superintendencia Financiera**, not Supersociedades, so they
    are absent from these datasets and `fetch_financials` returns `[]`
    for them rather than fabricate figures.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🟢 Live (RUES BusquedaAvanzadaRM → DetalleRM) |
| Lookup by NIT (`VAT` / `COMPANY_NUMBER`) | 🟢 Live (RUES BusquedaAvanzadaRM → DetalleRM) |
| Financials | 🟢 Live for Supersociedades filers (structured NIIF statements, 2015→latest); `[]` for SFC-supervised entities and unknown NITs |

## Test companies (real)

Registry (RUES) — search + lookup:

- **Ecopetrol S.A.** — NIT `899.999.068-1` — state-owned oil & gas.
- **Bancolombia S.A.** — NIT `890.903.938-8` — largest Colombian bank.
- **Grupo Argos S.A.** — NIT `890.900.266-3` — infrastructure
  conglomerate.
- **Avianca Group International Limited (Avianca Holdings)** — NIT
  `890.100.577-6` — flag carrier.

Financials (Supersociedades) — a company that files with Supersociedades
(not SFC-supervised), so all three methods return live data end-to-end:

- **Alpina Productos Alimenticios S.A.S. BIC** — NIT `860.025.900-2` —
  dairy/food manufacturer. Files entity-level NIIF Plenas statements;
  FY2023–FY2025 all present (e.g. FY2024 total assets ≈ 1.43 trillion
  thousand-COP, revenue ≈ 2.10 trillion thousand-COP).

All NIT check digits are verified by the adapter's `_nit_check_digit`
function (see unit tests in `packages/adapters/co/tests/test_co.py`); the
DV returned by RUES is used directly when present.

## Status

🟢 **Live** for RUES lookup + name search and for Supersociedades NIIF
financials. Financials are `[]` for SFC-supervised entities (see below)
and for NITs with no filed statements — never fabricated.

## Phase-2 follow-ups

1. **SFC-supervised financials**: entities supervised by the
   Superintendencia Financiera (banks, insurers, listed issuers) file
   XBRL/PDF with SFC, not Supersociedades. Wire the SFC "Entidades
   vigiladas" directory + report index so these get per-year
   `FinancialFiling` rows too.
2. **CIIU enrichment**: RUES exposes 1–4 CIIU codes per company
   (Colombia's adaptation of NACE Rev. 2). The adapter already
   surfaces them as `nace_codes`; cross-reference DANE's CIIU
   dictionary for human-readable labels in the future industry
   benchmarks table.
3. **DIAN VAT validation**: the Servicios en línea DIAN portal exposes
   a "Consulta inscripción RUT" page but it is JavaScript-rendered
   and behind a CAPTCHA. Out of scope until the Playwright pool
   (`packages/adapters/_base/browser.py`) lands.
4. **Sanctions/PEP**: wire `OpenSanctionsClient` to screen every
   Colombian principal returned by RUES. CO is on the OFAC SDN list
   for narcotics-related designations — this is high-signal for
   credit decisions.
