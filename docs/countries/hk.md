# 🇭🇰 Hong Kong — Companies Registry (ICRIS) + HKEX

## Identifiers

- `COMPANY_NUMBER` — **CR Number**, 7 digits, zero-padded
  (e.g. `0654177` = Tencent Holdings, `1299985` = AIA Group).
- `OTHER` — **BR Number** (Business Registration, IRD), 8 digits.
  Accepted for normalization but lookup is not free — IRD's BR Number
  Enquiry is paid. `lookup_by_identifier(OTHER, …)` raises
  `AdapterNotImplementedError` rather than fabricating a CR↔BR mapping.

## Sources

### Registry — Companies Registry "Cyber Search Centre" (ICRIS)
- Public landing: `https://www.icris.cr.gov.hk/csci/`
- Free tier: company name + CR number + status (active/dissolved/struck off).
- Paid tier: full extracts and certified documents, HK$8/doc.
- **Why we don't scrape it directly:** ICRIS is a JSF/SPA front-end that
  ships a per-session CSRF token, a `disable-devtool` script, and an
  Akamai bot-management interstitial. Plain `httpx` can fetch the landing
  page (we use it for the health probe), but the search and detail
  endpoints require browser-rendered JavaScript and the corresponding
  paid-API products. Per project rule #2 we don't use the paid API.

### Registry — OpenCorporates HK mirror (free tier)
- `https://api.opencorporates.com/v0.4/companies/search?jurisdiction_code=hk&q=…`
- `https://api.opencorporates.com/v0.4/companies/hk/{cr}`
- Free tier: 500 req/month, key required (`OPENCORPORATES_API_KEY`).
- HK records are sourced from ICRIS and refreshed periodically.
- Without the key, search/lookup raise `AdapterNotImplementedError` —
  we never fabricate data.

### Financials — HKEX (Hong Kong Exchanges and Clearing)
- `https://www.hkexnews.hk/` / `https://www1.hkexnews.hk/`
- Covers **listed issuers only**. Annual reports are filed by stock code
  via the Title Search backend:
  `https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=EN&category=0&market=SEHK&stockId={hkex}&from=YYYYMMDD&to=YYYYMMDD`
- The Title Search endpoint is a JSF page; we surface the canonical URL
  per year so a downstream PDF / browser-pool worker can resolve the
  actual filing list — never invent it. Unlisted HK companies return `[]`.
- **Resolving the HKEX stock code from a CR number:** if the caller
  passes a packed id (`CR:0654177/HKEX:0700`), we use it directly.
  Otherwise we ask OpenCorporates for the company's identifiers and look
  for a `Stock Exchange of Hong Kong` ticker. No ticker → `[]`.

## Auth & limits

- `OPENCORPORATES_API_KEY` — optional but required for real registry
  search / lookup. Free tier: 500 req/month.
- `requires_api_key = False` at the adapter level — without the OC key
  the adapter still passes a health check (in `degraded` state) and
  `fetch_financials` still works for callers who supply the HKEX code.
- We throttle to **30 req/min** (`rate_limit_per_minute = 30`) to be
  polite to both ICRIS and HKEX.
- robots.txt / ToS: ICRIS ToS prohibits redistribution of paid data —
  we only touch the free landing page. HKEX permits read-only access to
  the public news site.

## Test companies (REAL)

- HSBC Holdings plc (UK parent, CR `0013977`); Hong Kong subsidiary
  The Hongkong and Shanghai Banking Corporation Ltd. (CR `0263876`).
- Tencent Holdings Ltd. (CR `0654177`, HKEX `0700`).
- AIA Group Ltd. (CR `1299985`, HKEX `1299`).
- CK Hutchison Holdings / Cheung Kong Holdings (CR `0001392`).

## Status

✅ **Live** — health probe (ICRIS landing) + financials URL synthesis
   for listed issuers via HKEX Title Search.
🟡 **Partial** — `search_by_name` + `lookup_by_identifier(COMPANY_NUMBER)`
   are powered by the free OpenCorporates HK mirror; without
   `OPENCORPORATES_API_KEY` both raise `AdapterNotImplementedError`.
🔒 **Blocked (paid)** — full ICRIS extracts, BR-number IRD lookup, and
   listed-issuer XBRL/PDF parsing all sit behind paid HK Government
   gateways and are out of scope for the MVP.

**Recommended next step:** add a Playwright pool entry for
`www.icris.cr.gov.hk/csci/` so the free name+CR fields can be scraped
without the OpenCorporates dependency, and a HKEX news-feed parser so
the `document_url` we synthesize today resolves to actual filing PDFs
for the LLM context.
