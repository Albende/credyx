# South Africa — CIPC BizPortal + JSE

## Identifier

- Primary type: `COMPANY_NUMBER`
- Format: `YYYY/NNNNNN/NN` (year of incorporation / sequence / entity-type
  suffix, e.g. `/06` = (Pty) Ltd, `/07` = public company, `/08` = NPC).
  Sequences are zero-padded to 7 digits when stored canonically
  (e.g. Naspers `1925/0001431/06`).
- Secondary type: `VAT` — 10 digits, must start with `4` (SARS rule).
  Lookup-by-VAT is not implemented (SARS has no free validation API).

## Sources

### CIPC BizPortal (free, scrape)

- URL: https://www.bizportal.gov.za/
- Auth: none
- Rate limit: self-throttled to 30 req/min (no published limit; BizPortal
  is operated by the Department of Small Business Development and shares
  CIPC's live database).
- robots.txt / ToS: BizPortal exists to serve public company-information
  queries; no public API. The HTML form is the only free machine-accessible
  route. Markup changes occasionally — the adapter degrades to a clear
  `501 not_implemented` on unrecognized layouts rather than guessing.

### CIPC eServices (paid — skipped)

- URL: https://eservices.cipc.co.za/
- Sells full company extracts and annual financial statements per document.
  Not used: violates the MVP no-paid-API rule.

### JSE (Johannesburg Stock Exchange) — listed issuers only

- URL: https://www.jse.co.za/listed-companies
- Annual reports + SENS announcements are free for listed companies, but
  there is no free public CIPC-registration → JSE-share-code map and the
  JSE listing page is JavaScript-rendered. The adapter therefore returns
  `[]` from `fetch_financials` and surfaces the JSE listed-companies page
  as a manual `source_url` hint.

### SARS (tax authority)

- VAT validation endpoint requires an authenticated eFiling account; not
  publicly queryable. Skipped.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | DEGRADED | BizPortal HTML scrape; brittle. |
| `lookup_by_identifier` (COMPANY_NUMBER) | DEGRADED | BizPortal HTML scrape. |
| `lookup_by_identifier` (VAT) | NOT_IMPLEMENTED | SARS has no free API. |
| `fetch_financials` | NOT_IMPLEMENTED | Paid CIPC eServices required; JSE has no free programmatic surface. |

## Test companies

- Naspers Limited — `1925/001431/06` (JSE: NPN)
- Standard Bank Group Limited — `1969/017128/06` (JSE: SBK)
- MTN Group Limited — `1994/009584/06` (JSE: MTN)
- Sasol Limited — `1979/003231/06` (JSE: SOL)

## Status

DEGRADED — search + reg-number lookup via BizPortal scrape (best-effort).
Financials gated behind paid CIPC eServices.

**Recommended next step:** Phase 2 — integrate CIPC eServices once a paid
B2B agreement is in place; in parallel, wire JSE SENS / annual-report PDFs
into the PDF text extraction pipeline so listed-issuer financials become
usable without leaving the free tier.
