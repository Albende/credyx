# Ecuador — SUPERCIAS + SRI

## Identifier

- Type: `VAT` (primary — RUC doubles as the Ecuadorian corporate tax /
  VAT identifier) with `COMPANY_NUMBER` exposed as an alias.
- Format: **RUC** (Registro Único de Contribuyentes). **13 digits**,
  layout `PPCCCCCCCCDDD001`:
  - `PP` (digits 1–2): province code (01–24).
  - Digit 3: contributor class. `9` = sociedad / persona jurídica,
    `6` = institución pública, `0–5` = persona natural.
  - Digits 4–10: body identifier.
  - Last three digits: establishment suffix — for the head office this
    is always `001`.
- The adapter accepts every common rendering — `1790010937001`,
  `179.001.0937-001`, `EC 1790010937001` — and validates only on
  length + digit-only content. SUPERCIAS itself is the source of truth
  on RUC existence; we deliberately do not enforce a province-code
  range, because several legacy public-sector RUCs predate the modern
  banding.

## Sources

- **SUPERCIAS** (Superintendencia de Compañías, Valores y Seguros) —
  `https://www.supercias.gob.ec/` / Portal de Consultas at
  `https://appscvsmovil.supercias.gob.ec/portalConsultas/`.
  - **Auth**: none. **Cost**: free.
  - **Endpoints used**:
    - `GET /PortalInformacion/consulta/companias/{ruc}` — direct
      lookup. Returns company status, legal form, capital, registered
      address, principal CIIU.
    - `GET /PortalInformacion/consulta/companias/buscar?expresion={name}&tipo=razon_social`
      — name search.
    - `GET /PortalInformacion/consulta/informacion_economica?ruc={ruc}`
      — catalog of filed annual reports ("Información Económica"),
      including links to free PDF/Excel downloads.
  - Both lookup and search back the public Consultas web form. The
    JSON envelopes shift between deployments, so the adapter accepts
    several common keys (`companias`, `data`, `items`, `registros`,
    top-level array) and falls back to a defensive HTML parse of the
    portal's table layout when JSON is not returned. If neither
    parse succeeds, `AdapterNotImplementedError` is raised — never
    invent.
  - **Rate limit**: undocumented; we self-throttle at 30 req/min.
- **SRI** (Servicio de Rentas Internas) —
  `https://srienlinea.sri.gob.ec/sri-en-linea/SriRucWeb/ConsultaRuc/`
  - Public RUC validator. Useful as a coverage cross-check; not yet
    wired in because SUPERCIAS already returns more structured data
    for the sociedad subset that matters for credit risk.
- **Bolsa de Valores de Quito (BVQ)** —
  `https://www.bolsadequito.com/` — listed-company filings.
- **Bolsa de Valores de Guayaquil (BVG)** —
  `https://www.bolsadevaloresguayaquil.com/` — listed-company filings.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | Live (SUPERCIAS portal) |
| Lookup by RUC (`VAT` / `COMPANY_NUMBER`) | Live (SUPERCIAS portal) |
| Financials | Live — SUPERCIAS Información Económica catalog (free PDF/Excel) |

## Test companies (real)

- **Banco Pichincha C.A.** — RUC `1790010937001` — largest private bank.
- **Corporación Favorita C.A.** — RUC `1790016919001` — leading retailer.
- **Cervecería Nacional CN S.A.** — RUC `1790000017001` — brewery
  (AB InBev subsidiary).
- **Holcim Ecuador S.A.** — RUC `0990000180001` — cement (Holcim Group).

## Status

Live for SUPERCIAS lookup, name search, and free annual-report
catalog. Financials are surfaced as `FinancialFiling` rows pointing
at the SUPERCIAS-hosted documents; PDF text extraction is a Phase-2
addition that plugs into the shared pipeline once available.

## Phase-2 follow-ups

1. **PDF parsing**: SUPERCIAS Información Económica is mostly PDFs.
   Once the project-wide PDF pipeline ships (see CLAUDE.md
   cross-cutting infra), pass the extracted text per year to the
   LLM via `pdf_text_excerpts`.
2. **CIIU enrichment**: SUPERCIAS records carry a primary CIIU 4.0
   code; cross-reference INEC's Ecuadorian CIIU dictionary for the
   industry-benchmark table.
3. **SRI validation**: if a RUC is missing from SUPERCIAS but
   present in SRI it almost always represents a natural-person or
   public-sector entity outside SUPERCIAS's supervisory scope. Wire
   the SRI consolidated endpoint as a secondary lookup to label
   those rather than return `null`.
4. **BVQ / BVG filings**: scrape per-issuer prospectus and quarterly
   filings for the ~30 listed companies. Brittle scrape — gate
   behind the Playwright pool.
5. **Sanctions/PEP**: wire `OpenSanctionsClient` to screen every
   Ecuadorian principal and director returned by SUPERCIAS.
