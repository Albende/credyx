# 🇨🇭 Switzerland — Zefix (Central Business Names Index)

## Identifier

- Type: `COMPANY_NUMBER` (UID, primary) and `VAT` (same 9-digit core + ` MWST`/`TVA`/`IVA` suffix).
- Format: `CHE-XXX.XXX.XXX` — 9 digits with a mod-11 check digit. Example: `CHE-105.909.036` = Nestlé S.A.

## Sources

- https://www.zefix.admin.ch/ZefixPublicREST/ (swagger UI: `/swagger-ui/index.html`, OpenAPI: `/v3/api-docs`)
  - Search: `POST /api/v1/company/search` (JSON body `{"name": "...", "languageKey": "en"}`)
  - Lookup: `GET /api/v1/company/uid/{CHE-XXX.XXX.XXX}`
- **Auth**: HTTP Basic — **free registration required** (verified 2026-07-20: unauthenticated
  calls return `401` with `WWW-Authenticate: Basic realm="ZefixPublicREST"`).
  Request credentials by emailing **zefix@bj.admin.ch**; a test environment exists at
  `https://www.zefixintg.admin.ch/ZefixPublicREST/`.
  Set env vars `CH_ZEFIX_USERNAME` and `CH_ZEFIX_PASSWORD`. When they're missing the
  adapter raises `AdapterError` with the registration instructions and
  `health_check` reports `degraded`.
- **Rate limit**: Not formally published; we self-throttle to 60 req/min.
- **robots.txt / ToS**: ZefixPublicREST is explicitly published for programmatic use
  (registration is free of charge).
- Listed-issuer annual reports: https://www.six-group.com/ (not yet wired).

## Test companies

- Nestlé S.A. — `CHE-105.909.036`.
- Roche Holding AG — `CHE-100.077.366`.
- Novartis AG — `CHE-103.867.266`.
- UBS Group AG — `CHE-273.166.589`.

## Status

🟡 **Live, credentials required** — search + lookup work via Zefix once
`CH_ZEFIX_USERNAME`/`CH_ZEFIX_PASSWORD` are set (free registration). Without
credentials every call fails fast with a clear registration message.
Financials return `[]`.

**Recommended next step:** Register the operator account, then scrape SIX issuer
pages for listed companies' annual-report PDFs and wire them into
`fetch_financials` (still free, but per-issuer HTML parsing).
