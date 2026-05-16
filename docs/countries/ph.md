# 🇵🇭 Philippines — SEC iView + PSE Edge

## Identifier

- Primary: `COMPANY_NUMBER` — SEC Registration Number issued by the
  Securities and Exchange Commission of the Philippines. Alphanumeric with
  an optional letter prefix (`CS`, `A`, `AS`, `AN`, or `PP`), 6-14 chars in
  practice. Examples: `CS200417653` (SM Investments), `CS197600007` (Ayala
  Corporation).
- Alias: `VAT` — 12-digit Taxpayer Identification Number (TIN) issued by
  the BIR. The TIN is **independent** of the SEC number; the iView record
  sometimes exposes both, in which case we surface the TIN under
  `identifiers` alongside the SEC number. VAT-only lookup falls back to a
  TIN string search and returns `None` if no match surfaces — we never
  guess a mapping.

Normalization: strip whitespace and hyphens; accept an optional leading
`PH` prefix; uppercase the body; require it to match `[A-Z0-9]{6,14}`.

## Sources

### Registry — SEC iView

- Base: `https://iview.sec.gov.ph`
- iView is the SEC's public viewer for corporate records and registered
  filings. It is a single-page app backed by undocumented JSON endpoints.
- **Auth**: none. Free.
- **Endpoints probed** (in order, first one that responds is used):
  - `GET /api/company/search?q={query}&limit={N}`
  - `GET /api/search?q={query}&limit={N}`
  - `GET /api/companies?name={query}&limit={N}`
  - `GET /api/company/{secNo}` and `GET /api/companies/{secNo}` for detail.
- **Headers**: the JSON endpoints reject requests without browser-style
  `Accept`, matching `Referer`, and `Origin` — we send all three.
- **Rate limit**: not formally documented; we throttle to 30 req/min
  (`rate_limit_per_minute = 30`) to stay polite.
- **Returns**: SEC number, company name, registered office address,
  authorised / paid-up capital, registration date, corporation type, PSIC
  industry code, and company status.
- **Caveat**: the JSON shape is not stable — the adapter probes a handful
  of common key spellings (`companyName` / `company_name` / `name`, etc.)
  rather than committing to one. Anything we cannot read is exposed via
  `CompanyDetails.raw`.

### Financials — PSE Edge

- Base: `https://edge.pse.com.ph` (Edge API)
- Public site: `https://www.pse.com.ph`
- **Auth**: none.
- **Coverage**: **listed companies only** (SM, AC, BDO, JFC, …). For
  unlisted Philippine companies there is no free official financial
  source — `fetch_financials` returns `[]` rather than invent data. iREPORT
  (the SEC's paid filings portal) is out of scope per the project's
  no-paid-APIs rule.
- We probe each year over the requested window against
  `https://www.pse.com.ph/stockMarket/companyInfoSecurityProfile.html?cmpy_id={symbol}&security_id={symbol}&year={year}`
  and only emit a filing when the page returns 200 with a recognisable
  annual-report marker. The page is a SPA so we cannot extract structured
  XBRL from the HTML — we return the canonical URL for downstream
  PDF/scrape processing.
- **Ticker resolution**: SEC iView does not consistently expose a PSE
  ticker. The adapter reads any of `pseSymbol` / `stockSymbol` /
  `tickerSymbol` / `symbol` from the SEC record and accepts it only when
  it looks like a real 1-6-char A-Z[A-Z0-9]\* token.

## Test companies

- SM Investments Corporation — `CS200417653` (PSE: SM)
- Ayala Corporation — `CS197600007` (PSE: AC)
- BDO Unibank, Inc. — `CS196700106` (PSE: BDO)
- Jollibee Foods Corporation — `CS197802327` (PSE: JFC)

## Status

✅ **Live** — search + lookup via SEC iView (real data, no auth). JSON
shape is undocumented so the adapter is defensive about key naming.
🟡 **Partial** — financials best-effort: PSE Edge URLs for listed firms
only; unlisted firms return `[]`. A PSE ticker must be present on the SEC
record for financials to resolve.

**Recommended next steps:**

1. Cache a SEC-number → PSE-ticker mapping nightly (PSE publishes the
   listed-companies list) so financials work even when iView omits the
   symbol.
2. Plug a PSE Edge annual-report PDF/iXBRL parser into
   `packages/risk/xbrl_*` so listed filings become `structured_data`
   instead of opaque URLs. PSE's "PSE EDGE" portal exposes 17-A / 17-Q
   filings as PDF — needs the project-wide PDF pipeline first.
3. Reconsider SEC iREPORT (paid) for non-listed coverage during Phase 2,
   subject to the no-paid-APIs constraint being relaxed.
