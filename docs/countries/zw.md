# 🇿🇼 Zimbabwe — ZSE (listed) + Companies Registry probe

## Identifiers

- `COMPANY_NUMBER` — Companies and Other Business Entities Registry
  alphanumeric (issued by the registry under the Companies and Other
  Business Entities Act, Chapter 24:31). No canonical regex; mixed
  alpha-numeric with optional prefixes.
- `VAT` — ZIMRA Business Partner Number (BPN), the tax-side identifier.
  Validation requires authenticated ZIMRA portal access.

## Sources

- **Zimbabwe Stock Exchange** — https://www.zse.co.zw/
  - Listed-companies index page exposes every ZSE issuer (ticker +
    company name + profile link). Annual reports are linked from each
    issuer profile.
  - **Auth**: None.
  - **Rate limit**: Not published; adapter throttles to 30 req/min and
    relies on `get_with_retry`'s exponential backoff for transient errors.
  - **robots.txt / ToS**: Public market-disclosure data; respectful UA
    set via the shared HTTP client.
- **Companies and Other Business Entities Registry** —
  https://www.companies.gov.zw/
  - Homepage only; structured search and full-extract delivery are paid
    paper / eGovernment channels, not a public JSON API.
  - Adapter raises `AdapterNotImplementedError` instead of scraping a
    surface that doesn't return reliable, structured data.
- **ZIMRA** — https://www.zimra.co.zw/
  - TIN/BPN validator is gated behind authenticated tax-portal sessions.
    Out of scope for the free MVP.
- **Victoria Falls Stock Exchange (VFEX)** — sibling USD-denominated
  market; not yet wired but the same adapter pattern would apply.

## Test companies (REAL)

| Issuer | ZSE ticker |
|--------|-----------|
| Econet Wireless Zimbabwe Limited | `ECO` |
| Delta Corporation Limited | `DLTA` |
| CBZ Holdings Limited | `CBZ` |
| Innscor Africa Limited | `INN` |

## Status

🟡 **Partial / DEGRADED** — search and financial-pointer retrieval
work for ZSE-listed issuers. Registry lookups by `COMPANY_NUMBER` and
ZIMRA BPN lookups by `VAT` raise `AdapterNotImplementedError` — no
fabricated fallback.

**Capabilities**

- `search_by_name` — substring match against the ZSE listed-companies
  page (ticker + issuer name).
- `lookup_by_identifier` — always `AdapterNotImplementedError` (gated
  upstream registries).
- `fetch_financials` — for a known ZSE ticker, returns a single
  `FinancialFiling` pointing at the issuer profile URL where annual
  reports are attached. Currency `USD` (ZSE quotes in USD post-2023).
  No structured ratios — the PDF pipeline will extract them
  downstream once wired.
- `health_check` — probes `https://www.zse.co.zw/listed-companies/`.

**Known gaps / next steps**

- Companies and Other Business Entities Registry direct integration
  awaits either (a) the eGovernment B2B feed under
  https://egov.gov.zw or (b) explicit per-company paper requests.
- ZIMRA BPN validator requires a registered tax-agent session; not
  feasible without commercial credentials.
- Per-filing PDF discovery on issuer profiles needs the HTML parser
  for ZSE issuer-detail pages (deferred until the global PDF pipeline
  lands).
- VFEX coverage is a thin addition once ZSE is solid — same HTML
  pattern, different host.
