# Ghana — RGD + GRA + GSE

## Identifier

- Types: `COMPANY_NUMBER` (RGD registration number), `VAT` (GRA TIN).
- RGD format: prefix + digits, e.g. `CS123456789` (Company limited by
  Shares), `CG...` (Company limited by Guarantee), `PS...` (Partnership),
  `BN...` (Business Name). Prefix tags the entity type, followed by 6–12
  digits.
- GRA TIN format: `[C|P]NNNNNNNNNN` — one letter (`C` company, `P`
  person) followed by 10 digits. Example: `C0001234567`. Newer
  individual TINs use the Ghana Card PIN (`GHA-NNNNNNNNN-N`); companies
  still receive the legacy `C` format.

## Sources

- https://rgd.gov.gh/ — Registrar General's Department public portal.
- https://eregistrar.rgd.gov.gh/ — eRegistrar (login-gated extracts).
- https://gra.gov.gh/ — Ghana Revenue Authority TIN validator (partial).
- https://gse.com.gh/ — Ghana Stock Exchange (free annual reports for
  listed issuers).
- **Auth**:
  - RGD / eRegistrar: requires a registered account; certified extracts
    are paid per document.
  - GRA: public TIN-checker page protected by CAPTCHA / session token;
    no JSON API.
  - GSE: public for listed-issuer annual-report links; per-issuer page
    is JS-rendered.
- **Rate limit**: None documented; we self-throttle to 30/min.
- **robots.txt / ToS**: RGD forbids automated scraping; GSE permits
  read-only access to public pages.

## Test companies (GSE tickers)

- MTN Ghana (Scancom PLC) — `MTNGH`
- GCB Bank PLC — `GCB`
- Ecobank Ghana PLC — `EGH`
- Total Petroleum Ghana — `TOTAL`

## Status

**Blocked / Degraded** — name search and identifier lookup raise
`AdapterNotImplementedError` (RGD gated, GRA CAPTCHA-protected).
`fetch_financials` returns `[]` until the PDF + browser pipeline lands;
GSE annual reports are PDF-only and the listing index is JS-rendered.

**Recommended next steps:**

1. Wire GSE listed-issuer annual-report PDFs through the planned
   Playwright pool + PDF extraction pipeline. GSE freely publishes
   reports for ~40 issuers — that alone unlocks the largest GH
   corporates by market cap (MTN Ghana, GCB Bank, Ecobank Ghana,
   Total Petroleum Ghana, etc.).
2. Phase-2: add a logged-in eRegistrar scraping worker for RGD
   extracts (Celery + cookie jar). Each extract has a per-document fee
   in GHS — needs a credit-budget layer before enabling.
3. GRA TIN validation realistically needs paid third-party access or
   a Playwright + CAPTCHA-solving worker — not in scope for the free
   MVP.
