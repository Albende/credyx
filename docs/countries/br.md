# 🇧🇷 Brazil — Receita Federal (via BrasilAPI) + CVM

## Identifier

- Type: `VAT` (primary, since CNPJ doubles as the corporate tax ID) plus
  `COMPANY_NUMBER` as an alias.
- Format: **CNPJ** — 14 digits, displayed as `XX.XXX.XXX/XXXX-XX`.
- Validation: two trailing check digits (weighted sum mod 11). The
  adapter normalizes input (strips punctuation) and verifies the
  checksum before any HTTP call.

## Sources

- **Primary**: BrasilAPI — `https://brasilapi.com.br/api/cnpj/v1/{cnpj}`
  - Community-maintained mirror of the official Receita Federal CNPJ
    dataset.
  - **Auth**: none.
  - **Rate limit**: ~3 req/s, no key required.
- **Fallback**: ReceitaWS — `https://www.receitaws.com.br/v1/cnpj/{cnpj}`
  - Same dataset, slightly different shape. Used only when BrasilAPI
    returns 5xx. Free tier is 3 req/min — keep it as a last-resort
    fallback, not the hot path.
- **Listed-company filings**: CVM (Comissão de Valores Mobiliários).
  - Cadastro CSV: `http://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv`
    (Latin-1, `;`-delimited). Cached in-memory on first use; maps CNPJ
    → CVM code.
  - Per-company filings index: `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx?codigoCVM={code}`
  - Direct per-year DFP/ITR ZIP files are published at
    `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/` as yearly
    bundles covering *all* listed companies — not currently parsed by
    this adapter (a future Phase-2 add).

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🔴 Blocked — Receita Federal requires CAPTCHA |
| Lookup by CNPJ | ✅ Live (BrasilAPI primary, ReceitaWS fallback) |
| Financials | 🟡 Limited — index URL for CVM-listed companies; `[]` for closed-capital companies |

`search_by_name` raises `AdapterNotImplementedError` with a clear
message directing the caller to use direct CNPJ lookup. Per the
project's no-mock-data rule, we don't fabricate name-search results.

## Test companies

- Petrobras (Petróleo Brasileiro S.A.) — `33.000.167/0001-01`
- Vale S.A. — `33.592.510/0001-54`
- Itaú Unibanco Holding S.A. — `60.872.504/0001-23`
- Ambev S.A. — `07.526.557/0001-00`

## Status

✅ **Live** for CNPJ lookup. 🟡 financials limited to CVM-listed
companies (returns index URL, not parsed line items). 🔴 name search
blocked.

**Recommended next steps:**
1. Wire a Celery job that downloads the yearly CVM DFP bundle
   (`dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip`),
   filters by CNPJ, and populates `FinancialFiling.structured_data` with
   balance sheet / income-statement line items.
2. For closed-capital companies, evaluate adding a Junta Comercial
   per-state scraper (JUCESP, JUCESC, JUCERJA, ...) once browser pool
   infrastructure (`packages/adapters/_base/browser.py`) lands.
3. Consider integrating SERASA's open data feeds for negative-credit
   signals (paid in 2026; keep on the Phase-2 watchlist).
