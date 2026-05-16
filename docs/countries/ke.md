# 🇰🇪 Kenya — BRS + KRA + NSE

## Identifier

- Types: `COMPANY_NUMBER` (BRS registration number), `VAT` (KRA PIN).
- BRS format: prefix + digits, e.g. `PVT-XXXXXXX`, `CPR/XXXXX`,
  `C.XXXXX` — the prefix tags the entity type (PVT = private limited,
  CPR = company partnership, etc.).
- KRA PIN format: `[A|P]NNNNNNNNNL` — one letter (`P` person, `A`
  non-individual), 9 digits, one trailing check letter.
  Example: `P051092002G`.

## Sources

- https://brs.go.ke/ — Business Registration Service via eCitizen.
- https://itax.kra.go.ke/ — KRA iTax PIN checker.
- https://www.nse.co.ke/ — Nairobi Securities Exchange.
- **Auth**:
  - BRS: requires a logged-in eCitizen account; full extracts are paid
    per document (~KES 600).
  - KRA iTax: public PIN-checker page but protected by ASP.NET ViewState
    + CAPTCHA; no JSON API.
  - NSE: public for listed-issuer annual-report links; the per-company
    page is JS-rendered (Vue.js shell).
- **Rate limit**: None documented; we self-throttle to 30/min.
- **robots.txt / ToS**: BRS forbids automated scraping; NSE permits
  read-only access to public pages.

## Test companies (NSE tickers)

- Safaricom PLC — `SCOM`
- Equity Group Holdings Limited — `EQTY`
- East African Breweries Limited — `EABL`
- KCB Group Plc — `KCB`

## Status

🔴 **Blocked / Degraded** — name search and identifier lookup raise
`AdapterNotImplementedError` (BRS gated, KRA CAPTCHA-protected).
`fetch_financials` returns `[]` until the PDF + browser pipeline lands;
NSE annual reports are PDF-only and the listing index is JS-rendered.

**Recommended next steps:**

1. Wire NSE listed-issuer annual-report PDFs through the planned
   Playwright pool + PDF extraction pipeline. NSE freely publishes
   reports for ~60 issuers — that alone unlocks the largest KE
   corporates by market cap.
2. Phase-2: add a logged-in eCitizen scraping worker for BRS extracts
   (Celery + cookie jar). Each extract costs ~KES 600 — needs a
   credit-budget layer before enabling.
3. KRA PIN validation realistically needs paid third-party access
   (e.g. Norton-Rose's KRAcheck or aggregator APIs) — not in scope for
   free MVP.
