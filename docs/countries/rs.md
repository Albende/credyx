# 🇷🇸 Serbia — APR (Agencija za privredne registre)

## Identifiers

- `COMPANY_NUMBER` → **Matični broj (MB)** — 8 digits. Primary and the only
  identifier resolvable via the free open-data API (it is the record key).
- **PIB** (9-digit tax id) is **not present** in the APR open datasets, so
  VAT lookup is not supported through the free source. (It only appears on
  the interactive `pretraga2.apr.gov.rs` portal, which geoblocks non-Serbian
  traffic — see below.)

Examples: NIS a.d. — MB `20084693`. Telekom Srbija — MB `17162543`.

## Sources

- **APR company register open data**
  `https://openapi.apr.gov.rs/api/opendata/companies`
  Free, no auth, no key. One JSON document (`{DatumPreseka, Podaci}`) keyed
  by MB, one record per registered company (privredno društvo). Fields per
  record: `PoslovnoIme` (name), `SifraOpstine` / `NazivOpstine` (seat
  municipality), `NazivStatus` (status), `DatumOsnivanja` (founding date),
  `NazivPravneForme` (legal form), `SifraDelatnosti` (activity code).
  ~134k companies. Refreshed monthly (snapshot date in `DatumPreseka`).
- **APR financial-statements register (RGFI) open data**
  `https://openapi.apr.gov.rs/api/opendata/companies/financial-statements`
  Free, no auth, no key. JSON keyed by MB with the **latest** filed annual
  figures: `GodinaFi` (year), `PoslovnaImovina` (total assets), `Kapital`
  (capital/equity), `Gubitak`, `UkupniPrihodi` (total revenue),
  `NetoDobitak` / `NetoGubitak` (net profit / loss),
  `ProsecanBrojZaposlenih` (avg employees). **Amounts are in thousands of
  RSD** — the adapter scales to absolute RSD. ~123k companies. Banks and
  insurers report to the National Bank (NBS), not RGFI, so they are absent
  from this dataset (e.g. Komercijalna/NLB banka has no RGFI record).
- **`pretraga2.apr.gov.rs`** (unified entity search + per-filing PDF
  download) — **unreachable**: the host completes the TLS handshake then
  drops the connection for non-Serbian IPs (verified via httpx *and* a real
  headless Chrome through FlareSolverr, both `ERR_CONNECTION_CLOSED`). It is
  geoblocked, so PDF filing documents are not surfaced. We never present a
  landing page as a company's filing.

**Auth**: None.
**Rate limit**: Soft. We throttle to 30 req/min. The datasets are bulk
snapshots with no server-side filtering, so the adapter downloads each
document once (~57 MB) and caches it in-process for 6 h; searches and
lookups run over the cached snapshot.

## Adapter capabilities

| Capability             | Status | Notes                                                     |
|------------------------|--------|-----------------------------------------------------------|
| `search_by_name`       | ✅     | Diacritic-folded substring match over the company dump.   |
| `lookup_by_identifier` | ✅     | By MB (COMPANY_NUMBER). PIB/VAT not in the free datasets.  |
| `fetch_financials`     | ✅     | Latest-year RGFI figures as unified `structured_data` (RSD). |

## Test companies (real)

| Company              | MB         | Notes                                        |
|----------------------|------------|----------------------------------------------|
| NIS a.d. Novi Sad    | 20084693   | Full register + RGFI financials.             |
| Telekom Srbija a.d.  | 17162543   | Full register + RGFI financials.             |
| NLB Komercijalna banka | 07737068 | Register only — bank, no RGFI record (NBS).  |

## Implementation notes

- The open-data API returns a single large JSON per endpoint keyed by MB;
  there is no per-company query parameter (`?maticniBroj=` etc. are
  ignored). The adapter caches the parsed snapshot in a module-level cache
  guarded by an asyncio lock so concurrent calls download it at most once.
- `fetch_financials` emits the risk engine's unified schema
  (`balance_sheet` / `income_statement` with absolute-RSD values) plus a
  `raw_concepts` block carrying the original APR fields and headcount. Only
  the latest filed year is exposed by the dataset, so one `FinancialFiling`
  is returned. `document_url` is `None` — the free API carries figures, not
  the PDF, and the PDF portal is geoblocked.
- Status is normalized to `active` / `ceased` from the Cyrillic/Latin
  `NazivStatus` values (`Активан`, `Брисан`, `У ликвидацији`, `У стечају`…).
- Address granularity is the seat municipality (`NazivOpstine`) — the open
  dataset does not carry a street address.

## Status

🟢 **Live** — search, lookup, and structured financials against the free
APR open-data API (`openapi.apr.gov.rs`). No API key.

**Recommended next step:** the RGFI open dataset exposes only the latest
filed year; historical years and the full balance-sheet/P&L line items
require the RGFI per-company report (behind the geoblocked portal) or a
Serbian-side proxy — a Phase-2 item.
