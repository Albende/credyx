# 🇮🇶 Iraq — Ministry of Trade + Iraq Stock Exchange

## Identifiers

- **Company Registration Number** (Ministry of Trade / Companies
  Registrar) — variable-length numeric string, mapped to
  `IdentifierType.COMPANY_NUMBER`.
- **ISX Ticker** — 3–6 alphanumerics for issuers listed on the Iraq
  Stock Exchange (e.g. `TASC`, `BIIB`, `IBSD`). Shares the
  `COMPANY_NUMBER` slot since callers typically only have one of the two.
- **TIN** (Tax Identification Number, General Commission of Taxes) —
  digit-only, mapped to `IdentifierType.VAT`.

## Sources

- **Ministry of Trade — Companies Registrar** — https://mot.gov.iq/
  - Operates the Iraqi commercial register. The customer-facing portal
    is Arabic-only and gates company detail records behind in-person
    validation. No documented public JSON API.
  - **Auth**: in-person / paid intermediary.
  - **Rate limit**: not published. Adapter throttles to 20 req/min for
    any future use.
  - **robots.txt / ToS**: not crawler-friendly; we do not scrape.
- **General Commission of Taxes (GCT)** — https://tax.mof.gov.iq/
  - TIN issuance authority. No free public TIN validator exposes
    structured details.
- **Iraq Stock Exchange (ISX)** — https://www.isx-iq.net/
  - Publishes annual reports for TASI-style listed issuers as PDFs on a
    per-company profile page. Catalogue is served by a session-bound
    Java portal whose per-year filing list is rendered client-side, so
    structured extraction needs a headless browser.

## Test companies (REAL)

| Company | ISX Ticker | Notes |
|---------|------------|-------|
| Asiacell Communications PJSC | `TASC` | Telecoms, ISX-listed |
| Iraqi Islamic Bank for Investment and Development | `BIIB` | Bank |
| Baghdad Soft Drinks | `IBSD` | Beverages |

## Status

🟡 **Best-effort identifier validation only.** No free public data
source exposes structured Iraqi registry details, and ISX annual-report
extraction requires the browser pool described in the project roadmap.

**Capabilities**

- `search_by_name` — raises `AdapterNotImplementedError`. Ministry of
  Trade has no public name-search JSON; ISX surfaces only listed
  issuers.
- `lookup_by_identifier`:
  - `COMPANY_NUMBER` (registry number or ISX ticker) — validates format
    then raises `AdapterNotImplementedError` because no free endpoint
    exposes structured fields.
  - `VAT` (TIN) — validates digit-only format then raises
    `AdapterNotImplementedError` for the same reason.
- `fetch_financials` — returns `[]`. The ISX portal renders the
  per-year filing list client-side and requires a session; until the
  Playwright pool lands we will not fabricate placeholder filings.

**Known gaps / next steps**

1. Headless-browser scrape of the ISX per-issuer profile pages once
   `packages/adapters/_base/browser.py` is in place — annual reports
   are public PDFs in IQD.
2. Investigate datasets published on data.gov.iq for cross-reference
   enrichment.
3. Cross-reference Iraqi entities against the global GLEIF (LEI) feed
   for LEI-bearing issuers as a free enrichment layer.
4. Evaluate the Iraqi Securities Commission (ISC) site for additional
   regulatory disclosures beyond what ISX hosts.
