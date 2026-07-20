# 🇧🇷 Brazil — Receita Federal (via DadosBrasil + BrasilAPI) + CVM

## Identifier

- Type: `VAT` (primary, since CNPJ doubles as the corporate tax ID) plus
  `COMPANY_NUMBER` as an alias.
- Format: **CNPJ** — 14 digits, displayed as `XX.XXX.XXX/XXXX-XX`.
- Validation: two trailing check digits (weighted sum mod 11). The
  adapter normalizes input (strips punctuation) and verifies the
  checksum before any HTTP call.

## Sources

- **Name search**: DadosBrasil open API —
  `https://api.dadosbrasil.net/api/v1/companies?q={term}`
  - Open-data mirror of the official Receita Federal CNPJ dataset,
    re-imported on each monthly release. Full-text match over legal and
    trade names; returns the 14-digit CNPJ (`tax_id`), UF and status.
  - **Auth**: none.
  - The backend is intermittently reported as "database temporarily
    unavailable" (sometimes surfaced as a stalled connection). The
    down-windows are transient at the per-request level, so the adapter
    retries across fresh clients with a progressive backoff
    (`_DADOSBRASIL_ATTEMPTS`) to ride them out. During a sustained
    multi-minute outage search returns `[]`; there is no key-free
    fallback name-search source for BR (cnpja/CNPJ.ws search is
    key-gated; Casa dos Dados is Cloudflare-walled and ToS-grey).
- **Lookup by CNPJ**: BrasilAPI — `https://brasilapi.com.br/api/cnpj/v1/{cnpj}`
  - Community-maintained mirror of the official Receita Federal CNPJ
    dataset. **Auth**: none. **Rate limit**: ~3 req/s.
  - **Fallback**: ReceitaWS — `https://www.receitaws.com.br/v1/cnpj/{cnpj}`
    (same dataset, slightly different shape). Used only when BrasilAPI
    returns 5xx. Free tier is 3 req/min — last-resort only.
- **Listed-company filings**: CVM (Comissão de Valores Mobiliários).
  - Cadastro CSV: `https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv`
    (Latin-1, `;`-delimited). Cached in-memory on first use; maps CNPJ
    → CVM code and gates financials to CVM-registered companies.
  - Yearly DFP bundle: `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip`
    - Index member `dfp_cia_aberta_{year}.csv` carries the per-company
      filing record with `DT_REFER` and the official document link
      (`LINK_DOC` on rad.cvm.gov.br — a downloadable ENET package).
    - Statement members (`BPA`, `BPP`, `DRE`, consolidated `_con` with
      individual `_ind` fallback) carry the standardized account lines,
      parsed into `structured_data` (`balance_sheet`, `income_statement`)
      in the unified schema the risk engine reads. Values are scaled from
      thousands (MIL REAL) to absolute BRL.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | ✅ Live — DadosBrasil open data (Receita Federal CNPJ) |
| Lookup by CNPJ | ✅ Live (BrasilAPI primary, ReceitaWS fallback) |
| Financials | ✅ Live for CVM-listed companies (real DFP line items + document link); `[]` for closed-capital companies |

`fetch_financials` returns one `FinancialFiling` per reference year the
company actually filed (no fabricated years). Non-listed companies get
`[]` per the no-mock-data rule.

## Test companies

- Petrobras (Petróleo Brasileiro S.A.) — `33.000.167/0001-01`
- Vale S.A. — `33.592.510/0001-54`
- Itaú Unibanco Holding S.A. — `60.872.504/0001-23`
- Ambev S.A. — `07.526.557/0001-00`

## Status

✅ **Live** for name search (DadosBrasil), CNPJ lookup (BrasilAPI), and
financials (CVM DFP structured line items for listed companies).

**Recommended next steps:**
1. Cache downloaded DFP yearly bundles (13–15 MB each) out-of-band via a
   Celery job rather than pulling them on the request hot path, and
   persist parsed `structured_data` per company/year.
2. For closed-capital companies, evaluate a Junta Comercial per-state
   scraper (JUCESP, JUCESC, JUCERJA, ...) once browser-pool
   infrastructure lands.
3. Parse DFC (cash-flow) statement members to populate the `cash_flow`
   section of `structured_data`.
