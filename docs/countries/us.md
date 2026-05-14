# 🇺🇸 United States — SEC EDGAR

## Identifier

- Type: `CIK`
- Format: 10-digit, zero-padded. Example: 0000320193 = Apple Inc.

## Sources

- https://www.sec.gov/cgi-bin/browse-edgar ; https://data.sec.gov
- **Auth**: No key — but the SEC requires a descriptive User-Agent with contact email (`SEC_EDGAR_USER_AGENT`).
- **Rate limit**: 10 req/sec (global SEC rule).
- **robots.txt / ToS**: Allowed under the SEC's documented UA rule.

## Test companies

- Apple Inc. (0000320193); Microsoft (0000789019); Tesla (0001318605).

## Status

✅ **Live** — search + lookup + structured XBRL financials.

**Recommended next step:** Add state-level Secretary-of-State adapters (DE, CA, NY, TX, FL) — EDGAR only covers SEC-registered issuers.
