# 🇰🇼 Kuwait — MoCI + Boursa Kuwait

## Identifier

- Type: `COMPANY_NUMBER` (CR Number — Commercial Registration).
- Civil ID applies to individuals only; out of scope for company adapter.
- For Boursa-listed firms `fetch_financials` accepts the ticker symbol
  (e.g. `NBK`, `ZAIN`, `AGLT`, `KFH`) as `company_id`.

## Sources

- **MoCI Kuwait** — https://www.moci.gov.kw/
  - Auth: none, but the public CR portal is form-driven, partly bilingual,
    and does not expose a free structured JSON/REST API.
  - Status: **not usable** for deterministic search/lookup in MVP.
- **Boursa Kuwait** — https://www.boursakuwait.com.kw/
  - Auth: none. Per-issuer disclosure pages at
    `/en/issuer/{TICKER}` link to free annual reports (PDF).
  - Rate limit: respectful crawler — capped at 30/min.
  - robots.txt / ToS: public investor disclosures, allowed.

## Test companies

- National Bank of Kuwait — `NBK`
- Zain Group — `ZAIN`
- Agility Public Warehousing — `AGLT`
- Kuwait Finance House — `KFH`

## Status

🔴 **Blocked / Partial** —
- `search_by_name` ❌ — raises `AdapterNotImplementedError` (no free
  MoCI search API).
- `lookup_by_identifier` ❌ — raises `AdapterNotImplementedError`.
- `fetch_financials` 🟡 — returns a single Boursa Kuwait landing URL
  pointer for listed issuers; for unlisted companies it returns `[]`.
- `health_check` probes `boursakuwait.com.kw`.

**Recommended next step:** add a Playwright-driven scraper for MoCI's
public CR lookup once the browser-pool infrastructure (Phase 2) lands,
and parse Boursa Kuwait per-issuer disclosure pages to extract individual
PDF annual reports by year.
