# 🇺🇾 Uruguay — DGI + BVM

## Identifier

- Type: `VAT` (primary), `COMPANY_NUMBER` (alias).
- Format: **RUT** (Registro Único Tributario) — 12 digits, no separators
  in the canonical form. Common decorations (dots, dashes, the `UY`
  country prefix) are accepted and stripped by `_normalize_rut`.

## Sources

- **DGI — Dirección General Impositiva**
  - Public RUT consultation REST: `https://servicios.dgi.gub.uy/JSConsRUTRest/rest/consulta?rut={RUT}`
  - HTML facing form: `https://www.dgi.gub.uy/wdgi/page?2,principal,consulta-publica-de-rut,O,es,0,`
  - **Auth**: None.
  - **Rate limit**: Undocumented; the adapter throttles to 30 req/min.
  - **robots.txt / ToS**: The consultation is explicitly publicly
    available; we send a polite User-Agent and `Referer`.
- **BVM — Bolsa de Valores de Montevideo**
  - Issuers landing: `https://www.bvm.com.uy/emisores/`
  - Free annual reports for listed issuers (no per-issuer JSON feed,
    surfaced as a discovery URL on `FinancialFiling.document_url`).

## Test companies

- ANCAP (Administración Nacional de Combustibles, Alcohol y Pórtland) — RUT `215521240017`.
- Banco República (BROU) — RUT `211003140017`.
- UTE (Administración Nacional de Usinas y Trasmisiones Eléctricas) — RUT `211003900015`.
- ANTEL (Administración Nacional de Telecomunicaciones) — RUT `215521280011`.

## Capabilities

| Capability   | Status | Notes |
|--------------|--------|-------|
| Search by name | ❌ | DGI offers no free name-search API; raises `AdapterNotImplementedError`. |
| Lookup by RUT  | ✅ | DGI REST consultation; raises `BlockedByRegistryError` if the service serves HTML. |
| Financials     | ⚠️ | BVM discovery URL only (listed issuers); no structured ratios yet. |

## Status

✅ **Live** — RUT lookup against DGI; BVM URL pointer for financials.

**Recommended next step:** Scrape the per-issuer BVM "Información
Relevante" page to extract direct PDF links to annual reports for
listed companies (BROU, ANCAP, UTE, ANTEL all publish there), then wire
into the PDF text-extraction pipeline so the LLM can read filed
accounts text.
