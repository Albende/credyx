# 🇪🇬 Egypt — GAFI / ETA / EGX

## Identifier

- Primary: `COMPANY_NUMBER` — Commercial Registration Number (CR), variable digits.
- Secondary: `VAT` — Egyptian Tax Authority Tax ID, 9 digits, commonly
  formatted `NNN-NNN-NNN` (e.g. `200-118-815`).

## Sources

- **GAFI** (General Authority for Investment & Free Zones) — https://www.gafi.gov.eg/
  - Investor portal. Public data extremely limited; full CR records sit
    behind a sessioned web form. No documented JSON API.
- **ETA** (Egyptian Tax Authority) — tax verifier portal.
  - Partial public lookup, captcha-gated form submissions only.
- **EGX** (Egyptian Stock Exchange) — https://www.egx.com.eg/
  - Free disclosure pages and annual report PDFs for listed companies
    (Arabic + English). No documented JSON API; per-issuer pages are
    keyed by ticker symbol (`COMI`, `ETEL`, `EAST`, `TMGH`, …).
- **Auth**: None publicly. GAFI/ETA require interactive sessions.
- **Rate limit**: None documented. Adapter throttles to 30 req/min.
- **robots.txt / ToS**: EGX permits public access to disclosure pages.
  GAFI/ETA disallow automated harvesting of their gated areas.

## Test companies

- Commercial International Bank (CIB) — Tax ID `200-118-815`, EGX `COMI`.
- Telecom Egypt — Tax ID `200-194-841`, EGX `ETEL`.
- Eastern Company (Eastern Tobacco) — Tax ID `200-001-068`, EGX `EAST`.
- Talaat Moustafa Group — EGX `TMGH`.

## Status

🔴 **Blocked** — no free national-registry API.
🟡 **Partial** — EGX disclosure URLs surfaced for listed tickers via
`fetch_financials`; PDF parsing not yet wired.

`search_by_name` and `lookup_by_identifier` raise
`AdapterNotImplementedError` and surface as HTTP 501 to clients.

## Recommended next steps

1. Wire a Playwright-backed scraper for EGX issuer pages to fetch the
   per-year annual-report PDFs, then pipe through the PDF text extractor
   (see `packages/risk` / Phase 2 infra notes in `CLAUDE.md`).
2. Evaluate paid GAFI/ETA channels in Phase 2 — out of scope today
   (no paid APIs in MVP).
3. Cross-reference Egyptian entities against OpenSanctions and GLEIF
   (LEI search) inside the risk engine before the LLM step.
