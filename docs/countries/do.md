# 🇩🇴 Dominican Republic — DGII + BVRD

## Identifier

- Type: `VAT` (RNC) — also surfaced as `COMPANY_NUMBER`.
- Format: 9–11 digits (corporate RNC = 9; cédula-derived RNC = 11).
  Examples: `101009371` (Banco Popular Dominicano),
  `101015488` (Cervecería Nacional Dominicana).

## Sources

- **DGII** — Dirección General de Impuestos Internos: https://www.dgii.gov.do/
  Public RNC consultation page. No documented JSON API; the consultation
  form is a stateful ASP.NET WebForm. A daily master file `DGII_RNC.zip`
  is published with the full taxpayer roster — usable for offline
  name-search but too large for the request hot path.
- **BVRD** — Bolsa de Valores de la República Dominicana:
  https://www.bvrd.com.do/ — public issuer disclosures, no stable API,
  only listed companies (e.g. Refidomsa, EGE Haina).
- **Auth**: None.
- **Rate limit**: Self-imposed 30 req/min (DGII has no published limit
  but the page is fragile).
- **robots.txt / ToS**: Consultation page is public; bulk scraping is
  not encouraged. Use the published `DGII_RNC.zip` for bulk use cases.

## Test companies

- Banco Popular Dominicano — RNC `101009371`
- Cervecería Nacional Dominicana — RNC `101015488`
- Refidomsa — public (BVRD-listed)

## Status

🟠 **Degraded** —
- `search_by_name` → `AdapterNotImplementedError` (no name-search API).
- `lookup_by_identifier(VAT)` → best-effort scrape of the DGII
  consultation page; returns `None` when the stateful WebForm does not
  yield a populated record on a plain GET.
- `fetch_financials` → `[]` (BVRD per-issuer feeds not yet wired; no
  filings for unlisted companies).
- `health_check` → probes `dgii.gov.do`.

## Recommended next steps

1. Ingest the daily `DGII_RNC.zip` into Postgres on a nightly Celery job
   to back proper name search.
2. Build a BVRD disclosures fetcher for listed issuers
   (PDF/XBRL discovery + extraction).
3. If DGII consultation scraping is needed at volume, drive it via
   Playwright (see `packages/adapters/_base/browser.py` placeholder) to
   carry the ASP.NET viewstate and `__EVENTVALIDATION` tokens.
