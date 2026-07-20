# 🇰🇿 Kazakhstan — adata.kz + DFO financial-statements depository

## Identifier

- Type: `VAT` (primary) and `COMPANY_NUMBER` (alias) — both resolve to
  the BIN.
- Format: **BIN** (Бизнес-сәйкестендіру нөмірі / Бизнес-идентификационный
  номер) — exactly **12 digits**. Issued by the Ministry of Justice to
  every legal entity at registration. Natural persons receive an IIN of
  the same width — out of scope here.
- Some external sources prefix the BIN with `KZ`; the adapter strips it.

## Sources

- **adata.kz counterparty API** — `https://pk-api.adata.kz/api/v1/data/...`.
  The public backend of the adata.kz counterparty checker
  (`pk.adata.kz`). **Free, no API key, no session cookie** for the
  endpoints we use. adata aggregates the Kazakhstan legal-entity register
  from official open sources (stat.gov.kz, kgd.gov.kz, egov.kz).
  - `GET /api/v1/data/search?most_viewed_companies=0&keyword={q}` —
    full-text search by name **or** BIN. Returns BIN, name, address,
    director, status, registration date. Used for both `search_by_name`
    and `lookup_by_identifier` (a BIN keyword returns the single match).
  - `GET /api/v1/data/company/authorized-capital/short?id={bin}&initial=1`
    — charter capital + government-participation share (source: egov.kz).
- **DFO — Депозитарий финансовой отчётности** — `https://opi.dfo.kz`.
  Ministry of Finance financial-statements depository. Every
  public-interest organisation (listed issuers, banks, subsoil users,
  entities with state participation, etc.) files annual accounts here.
  Free, no key. JSON endpoints:
  - `GET /ru/opi/list?flBin={bin}` — resolve BIN → internal object id
    (HTML, server-rendered).
  - `GET /ru/report-json/{object}/get-plugins` — report taxonomies +
    counts. Annual accounts live under the **МСФО** (IFRS, financial
    orgs) and **665** (non-financial orgs) plugins.
  - `GET /ru/report-json/{object}/get-reports?pluginId=...` — filed
    reports (ReportId + load date) for a plugin.
  - `GET /ru/render-blocks/{object}/get-node-data?...&nodeId=1` — a
    report's info block, giving the authoritative reporting **year** and
    period.
- **Auth**: None. No API key anywhere.
- **Rate limit**: Self-imposed at 30 req/min.
- **robots.txt / ToS**: adata pk.adata.kz and opi.dfo.kz both serve the
  data we read to anonymous public users.

## Test companies

- КазМунайГаз (АО "НК "КазМунайГаз") — BIN `020240000555` (form 665)
- Kaspi (financial org, IFRS reports) — BIN `971240001315`
- Kazatomprom — BIN `970240000816`
- Air Astana (АО "ЭЙР АСТАНА", listed carrier, form 665) — BIN `010940000162`
- ТОО "TESM Company" — BIN `980440000757` (registry hit; **not** a
  public-interest filer, so `fetch_financials` returns `[]`)

## Status

🟢 **Live — search + lookup + financials.**

| Capability  | Status                                                    |
|-------------|-----------------------------------------------------------|
| Name search | ✅ Live via adata.kz counterparty API                     |
| BIN lookup  | ✅ Live via adata.kz (BIN keyword → single match)         |
| Financials  | ✅ DFO depository annual reports (public-interest filers)  |
| Health      | ✅ Probes adata.kz search with KazMunayGas BIN            |

## Limitations

- **Financials cover public-interest organisations only.** The DFO
  depository holds annual accounts for listed issuers, banks, subsoil
  users, state-participation entities and similar. Ordinary private LLPs
  do not file there — for those `fetch_financials` returns `[]` (the
  honest signal), never a fabricated filing.
- **Filing metadata, not decoded line items.** The adapter surfaces the
  reporting year, filing type (annual), currency (KZT), the DFO report
  metadata (report id, plugin, load date) and a report-specific
  `source_url`. It does **not** invent balance-sheet numbers. Decoding
  the DFO report node data (`nodeId=3` financial statements) into
  `structured_data` figures is a follow-up for the ratio engine.
- **`document_url` is left `None`.** DFO renders reports in an in-portal
  viewer rather than a single downloadable file, so we surface the
  report page `source_url` and do not claim a direct document download.
- **adata is an aggregator.** It mirrors official registers (stat.gov.kz,
  kgd.gov.kz, egov.kz). Data is best-effort and mixes Russian and Kazakh
  script; the adapter leaves text in whatever script the source returns.
- **Charter capital only for some entities.** adata surfaces it for a
  subset; `capital_amount` is `None` when absent, currency defaults KZT.

## Recommended next steps

1. Parse DFO report node data (`get-node-data nodeId=3`) into
   `structured_data` so the risk engine gets real ratios, not just
   filing metadata.
2. Ingest the DFO object index so financials resolve without the extra
   HTML search round-trip per lookup.
3. Add a KGD (tax authority) VAT-status probe as an automatic red flag
   when a counterparty is delisted as a VAT payer.
