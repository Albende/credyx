# 🇲🇩 Moldova — idno.md + statistica.md filings depository

## Identifier

- Type: `COMPANY_NUMBER` (IDNO — Identification Number), also acts as `VAT` / cod fiscal.
- Format: 13 digits. The first digit encodes the legal form
  (1 = SRL/SA and similar legal persons).
- Examples: 1003600005148 (Moldovagaz SA), 1003600066037 (Chişinău-Gaz SRL).

## Sources

- https://www.idno.md/ — community mirror of the ASP (Agenția Servicii
  Publice) state company register, keyed by IDNO. Free, no auth. Used for
  name search and per-IDNO lookup. **Sits behind Cloudflare**, so requests
  go through `fetch_with_bot_bypass` (FlareSolverr fallback at :8191).
  - Search: `GET /companii?q=<term>` (name, founder, or IDNO).
  - Detail: `GET /companie?idno=<IDNO>`.
- https://depozitar.statistica.md/ — **official Public Depository of
  Financial Statements** run by the National Bureau of Statistics. Its
  backend `https://depozitar-cabinet.statistica.md/api/public/v1` exposes
  filed annual financial statements per IDNO, **free and key-free**:
  - `GET /fs/economic-agent?idno=<IDNO>` → list of `{id, year, source}`
    (token-free).
  - `GET /fs/{id}` → full statement JSON: balance sheet (anexa1), P&L
    (anexa2), equity changes (anexa3), cash flow (anexa4) with real line
    items in MDL (token-free).
  - The `/fs` and `/ae` *search* endpoints require a Google reCAPTCHA v3
    token (verified server-side) and are therefore NOT used.
  - `/export/{pdf,csv,xbrl}` and attachment downloads are reCAPTCHA-gated.
- https://dataset.gov.md/ — CKAN open-data portal. The ASP register is
  published as weekly full-register XLSX dumps (~38 MB each, dataset
  `11736-...`); useful for bulk ingestion but too heavy for live search.
- **Auth**: None required for any of the sources above.
- **Rate limit**: Self-imposed 30 req/min.
- **Charset**: idno.md serves UTF-8 Romanian (Latin, with diacritics);
  `httpx`/FlareSolverr decode transparently.

## Test companies

- Moldovagaz SA — `1003600005148`
- Chişinău-Gaz SRL — `1003600066037`
- Ungheni-Gaz SRL — `1003609007411`
- Moldovatransgaz SRL — `1003607010109`

## Capabilities

| Capability     | Status | Notes |
|----------------|--------|-------|
| `search_by_name`         | ✅ | idno.md `/companii?q=…` via Cloudflare bypass. |
| `lookup_by_identifier`   | ✅ | idno.md `/companie?idno=…` detail scrape. |
| `fetch_financials`       | ✅ | statistica.md depository, annual filings with balance-sheet + P&L totals (MDL). |

## Status

🟢 **Live** — all three capabilities return real data, no API key required.
Financials cover entities that file with the National Bureau of Statistics
(most SRLs/SAs; note public-interest entities such as banks report to BNM
instead and may be absent from the depository).

**Recommended next steps:**
1. Ingest the weekly `dataset.gov.md` XLSX dump into Postgres so search is
   independent of idno.md / Cloudflare uptime.
2. Wire `/fs/{id}` line items into `packages/risk` so MDL statements feed
   the ratio engine directly (currency normalization to EUR needed).
