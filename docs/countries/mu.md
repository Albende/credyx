# 🇲🇺 Mauritius — ROC/CBRD + SEM

## Identifier

- Types: `COMPANY_NUMBER` (Business Registration Number, BRN),
  `VAT` (VRN issued by the Mauritius Revenue Authority).
- BRN format: one letter prefix (`C` company, `F` foreign, `P`
  partnership, etc.) followed by 5–12 digits. Example: `C07012345`.
- VRN format: 8 numeric digits as printed on MRA VAT certificates.
  Example: `12345678`.

## Sources

- https://onlinebrn.govmu.org/ — CBRD (Corporate and Business
  Registration Department) public name search.
- https://www.mra.mu/ — Mauritius Revenue Authority VAT services
  (login-only).
- https://www.stockexchangeofmauritius.com/ — Stock Exchange of
  Mauritius (Official + DEM markets).
- **Auth**:
  - CBRD onlinebrn: name search is exposed through a JSF/PrimeFaces
    page protected by rotated ViewState tokens; full extracts are paid
    per document.
  - MRA VAT: e-services portal requires a logged-in TAN account; there
    is no free public VRN inquiry endpoint.
  - SEM: public for listed-issuer pages and annual-report PDFs; the
    per-company page is JS-rendered.
- **Rate limit**: None documented; we self-throttle to 30/min.
- **robots.txt / ToS**: CBRD forbids automated scraping; SEM permits
  read-only access to public pages.

## Test companies (SEM tickers)

- MCB Group Limited — `MCBG`
- SBM Holdings Ltd (State Bank of Mauritius) — `SBMH`
- Air Mauritius Limited — `AIRM`
- Sun Limited — `SUNL`

## Status

🟡 **Degraded** — name search and BRN/VAT lookup raise
`AdapterNotImplementedError` (CBRD JSF-gated, MRA login-only). The
adapter surfaces SEM-listed issuers via ticker for both
`search_by_name` and `lookup_by_identifier`. `fetch_financials`
returns navigation pointers per recent FY (no fabricated numbers) for
SEM-listed tickers and `[]` otherwise.

**Recommended next steps:**

1. Wire SEM listed-issuer annual-report PDFs through the planned
   Playwright pool + PDF extraction pipeline. SEM freely publishes
   reports for the ~40 Official Market issuers plus DEM issuers — that
   unlocks the largest MU corporates by market cap (banks, hotels,
   sugar, conglomerates).
2. Phase-2: scrape the onlinebrn JSF flow with a stateful session
   (ViewState capture + cookie jar) for name search. Each paid extract
   (~MUR 200) needs a credit-budget layer before enabling.
3. MRA VRN validation realistically needs an authenticated TAN account
   for the MRA e-services portal — not in scope for the free MVP.
