# 🇸🇦 Saudi Arabia — MCI + ZATCA + Tadawul

## Identifiers

- **CR Number** (Commercial Registration) — 10 digits, mapped to
  `IdentifierType.COMPANY_NUMBER`. Common prefixes:
  - `10xxxxxxxx` — Riyadh-issued main CR (e.g. 1010150269 STC).
  - `20xxxxxxxx` — Eastern Province (e.g. 2052101140 Saudi Aramco).
  - `40xxxxxxxx` — Makkah, etc.
- **VAT** — 15 digits beginning with `3`. May be presented with an
  EU-style `SA` prefix; adapter strips it.
- **700 ID** — Establishment number used by GOSI / Ministry of Labour,
  10 digits beginning with `7`. Shares the `COMPANY_NUMBER` slot; the
  adapter labels it `700 Establishment Number` when detected.

## Sources

- **Ministry of Commerce (MCI)** — https://mci.gov.sa/en/eServices
  - Public name search and CR detail page exist but the structured
    fields are gated behind Nafath (Saudi national e-ID) login.
  - **Auth**: Nafath. Free in principle but not accessible from outside
    Saudi Arabia without a National ID / Iqama.
  - **Rate limit**: Not published. Adapter throttles to 30 req/min.
  - **robots.txt / ToS**: Disallows automated harvesting of session
    pages — we deep-link only.
- **CR Validator** — https://mc.gov.sa/ar/eservices/Pages/CRValidation.aspx
  - Validates a CR exists; gives status flag. Form is reCAPTCHA-gated.
- **ZATCA VAT Validator** — https://zatca.gov.sa/en/eServices
  - Form-based VAT TIN check, protected by Google reCAPTCHA. No
    structured JSON returned.
- **Tadawul / Saudi Exchange** — https://www.saudiexchange.sa/
  - Annual reports for TASI-listed issuers are published as PDFs on the
    per-issuer page. The catalogue is rendered client-side by Angular;
    there is no documented public JSON API.

## Test companies (REAL)

| Company | CR | Notes |
|---------|----|----|
| Saudi Arabian Oil Company (Aramco) | `2052101140` | TASI ticker 2222 |
| Saudi Telecom Company (STC) | `1010150269` | TASI ticker 7010 |
| Saudi National Bank (SNB) | `1010008668` | TASI ticker 1180 |
| Saudi Basic Industries Corp. (SABIC) | `1010010813` | TASI ticker 2010 |

## Status

🟡 **Best-effort lookup only.** No free public data source exposes
structured Saudi registry details without Nafath authentication or a
reCAPTCHA bypass.

**Capabilities**

- `search_by_name` — raises `AdapterNotImplementedError`. MCI name
  search is Nafath-gated; there is no free public JSON.
- `lookup_by_identifier`:
  - `COMPANY_NUMBER` (CR or 700) — validates format and returns a
    `CompanyDetails` whose `source_url` deep-links to the MCI public CR
    page. No fabricated fields.
  - `VAT` — validates format (15 digits, starts with 3; `SA` prefix
    stripped) and returns a `CompanyDetails` pointing at the ZATCA
    validator page.
- `fetch_financials` — returns `[]`. Tadawul annual reports require a
  browser pool (Angular SPA); not yet wired.

**Known gaps / next steps**

1. Headless-browser scrape of Tadawul issuer pages once
   `packages/adapters/_base/browser.py` lands — annual reports are
   public PDFs.
2. Investigate the Wathq commercial data API (https://api.wathq.sa/) —
   official Saudi B2B data service operated by MCI. It exposes CR,
   national address, GOSI and ZATCA endpoints under one umbrella but
   currently requires a paid subscription, so out of scope for the free
   MVP per the project's non-negotiable rule #2.
3. Cross-reference Saudi entities against the global GLEIF (LEI) feed
   for LEI-bearing issuers as a free enrichment layer.
