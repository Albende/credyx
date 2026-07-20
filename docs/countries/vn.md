# 🇻🇳 Vietnam — National Business Registration Portal (NBR) + Vietcap IQ

## Identifier

- Types: `COMPANY_NUMBER`, `VAT` — the same value (Mã số thuế / MST).
- Format: 10 digits issued by the General Department of Taxation. Branch
  units append a 3-digit suffix (e.g. `0300588569-001`), giving 13 digits
  total. The MST doubles as the business registration code.
- Examples: Vinamilk `0300588569`, Vingroup `0101245486`,
  Vietcombank `0100112437`, FPT `0101248141`.

## Sources

- https://thongtindoanhnghiep.co — community JSON wrapper around the NBR.
  - Endpoints: `/api/company?k={query}&p={page}` (name search, returns
    `LtsItems`) and `/api/company/{mst}` (per-company detail).
  - **Auth**: No.
  - **Cloudflare**: The whole site now sits behind a Cloudflare "Just a
    moment" JS challenge. The adapter routes every call through
    `fetch_with_bot_bypass` (FlareSolverr at `http://127.0.0.1:8191`), which
    returns the JSON wrapped in an HTML `<pre>` block; the adapter unwraps it.
  - **Rate limit**: Soft — adapter throttles to 30 req/min.
  - **Data quirk**: the record's `Title` is sometimes a stale branch/unit
    name, but the `SolrID` slug (`/{mst}-{legal-name-slug}`) always carries
    the registered legal name. The adapter uses that slug for the ticker join.
- https://iq.vietcap.com.vn/api/iq-insight-service — Vietcap IQ Insight
  service, the public data layer behind trading.vietcap.com.vn. Free, no key.
  - `/v2/company/search-bar?language=1` — full listed-company roster
    (ticker + Vietnamese legal name); used to resolve a tax code to its
    stock ticker by normalized legal-name match.
  - `/v1/company/{ticker}/financial-statement/metrics` — line-item
    dictionary (field code → English title), so canonical fields are mapped
    per company template (corp vs. bank vs. securities).
  - `/v1/company/{ticker}/financial-statement?section=BALANCE_SHEET` and
    `?section=INCOME_STATEMENT` — audited annual statements (`years` array),
    real as-filed figures in VND. Only listed issuers; unlisted firms → `[]`.
- https://dangkykinhdoanh.gov.vn — official NBR portal (HTML-only,
  not used directly; the wrapper above mirrors its data).

## Test companies

- Vinamilk — Vietnam Dairy Products JSC, MST `0300588569`, HOSE: `VNM`.
- Vingroup JSC, MST `0101245486`, HOSE: `VIC`.
- Vietcombank, MST `0100112437`, HOSE: `VCB`.
- FPT Corporation, MST `0101248141`, HOSE: `FPT`.

## Status

✅ **Live** — search + lookup via thongtindoanhnghiep.co (Cloudflare bypass);
financials via Vietcap IQ for listed issuers. `fetch_financials` returns one
`ANNUAL_REPORT` filing per year with real balance-sheet + income-statement
figures (VND) in `structured_data` (canonical schema + `raw_concepts`).
Unlisted firms return `[]`.

Verified live 2026-07-21: search "Vinamilk" → 10 real matches; lookup
`0300588569`; financials for VNM (Vinamilk) and FPT `0101248141` returned
real 2023–2025 statements. Tax-code → ticker join is an exact normalized
legal-name match (registry SolrID slug vs. Vietcap Vietnamese name), so it is
conservative: no confident match → `[]`, never a wrong company.

**Depends on:** FlareSolverr running at `FLARESOLVERR_URL`
(default `http://127.0.0.1:8191`) for the thongtindoanhnghiep.co calls.

**Recommended next step:** persist the Vietcap listing roster (2k rows) with
a TTL cache instead of the per-process in-memory cache, and add HOSE/HNX
annual-report PDF `document_url`s once a per-symbol disclosure index is wired.
