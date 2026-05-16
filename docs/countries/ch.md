# 🇨🇭 Switzerland — Zefix (Central Business Names Index)

## Identifier

- Type: `COMPANY_NUMBER` (UID, primary) and `VAT` (same 9-digit core + ` MWST`/`TVA`/`IVA` suffix).
- Format: `CHE-XXX.XXX.XXX` — 9 digits with a mod-11 check digit. Example: `CHE-105.927.350` = Nestlé S.A.

## Sources

- https://www.zefix.ch/ZefixPublicREST/
  - Search: `POST /api/v1/company/search` (JSON body `{"name": "...", "languageKey": "en"}`)
  - Lookup: `GET /api/v1/company/uid/{CHE-XXX.XXX.XXX}`
- **Auth**: No — fully free public REST API.
- **Rate limit**: Not formally published; we self-throttle to 60 req/min.
- **robots.txt / ToS**: ZefixPublicREST is explicitly published for programmatic use.
- Listed-issuer annual reports: https://www.six-group.com/ (not yet wired).

## Test companies

- Nestlé S.A. — `CHE-105.927.350` (VAT `CHE-105.927.350 MWST`).
- Roche Holding AG — `CHE-100.077.366`.
- Novartis AG — `CHE-103.867.266`.
- UBS Group AG — `CHE-273.166.589`.

## Status

✅ **Live** — search + lookup ✅ via Zefix. Financials return `[]`.

**Recommended next step:** Scrape SIX issuer pages for listed companies' annual-report PDFs and wire them into `fetch_financials` (still free, but per-issuer HTML parsing).
