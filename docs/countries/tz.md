# 🇹🇿 Tanzania — BRELA + TRA + DSE

## Identifiers

- `COMPANY_NUMBER` — BRELA Registration Number (primary).
- `VAT` — TRA TIN (10-digit Taxpayer Identification Number).

## Sources

- **BRELA** — Business Registrations and Licensing Agency.
  - Portal: https://orsbrela.brela.go.tz/
  - **Auth**: Interactive session with CAPTCHA on every search. No
    documented JSON / REST API.
  - **Status**: 🔴 Gated. Adapter raises `AdapterNotImplementedError`.
- **TRA** — Tanzania Revenue Authority.
  - Portal: https://www.tra.go.tz/
  - **Auth**: TIN validator is interactive only.
  - **Status**: 🔴 Gated. Adapter raises `AdapterNotImplementedError`.
- **DSE** — Dar es Salaam Stock Exchange.
  - Portal: https://www.dse.co.tz/
  - **Auth**: None — public investor-relations pages with PDF annual
    reports.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.
  - **Status**: 🟢 Used to surface annual-report landing pages for a
    small, manually verified roster of listed issuers.

## Test companies

All four are DSE-listed and used by the integration tests:

- **CRDB Bank PLC** — DSE ticker `CRDB`.
- **NMB Bank PLC** — DSE ticker `NMB`.
- **Tanzania Breweries Limited (TBL)** — DSE ticker `TBL`.
- **Vodacom Tanzania PLC** — DSE ticker `VODA`.

## Status

🟡 **Partial** — registry search/lookup unavailable; financials limited
to verified DSE listings.

**Capabilities**

- `search_by_name` — raises `AdapterNotImplementedError` (BRELA gated).
- `lookup_by_identifier` — raises `AdapterNotImplementedError` for both
  `COMPANY_NUMBER` and `VAT`.
- `fetch_financials` — for `company_id` in `{CRDB, NMB, TBL, VODA}`
  returns a single `FinancialFiling` pointing at the DSE issuer page
  (`source_url`). No fabricated numbers, period ends, or PDF URLs. For
  any other `company_id` returns `[]`.
- `health_check` — probes https://www.dse.co.tz/ and reports
  `DEGRADED` (search/lookup off, financials limited) when reachable.

## Currency

DSE issuers report in TZS (Tanzanian Shilling). Financial filings carry
`currency = "TZS"`; FX normalization to EUR is the responsibility of
`packages/risk` (see cross-cutting work item #5 in `CLAUDE.md`).

## Known gaps / next steps

1. **BRELA scraper.** OrSBrela can be navigated with Playwright +
   CAPTCHA solving; only worth doing if Tanzania becomes a Phase-2
   priority. Add to `packages/adapters/_base/browser.py` when built.
2. **TIN validation.** TRA exposes a session-based validator; a
   browser-pool implementation could verify TIN format + active status
   without scraping detail pages.
3. **DSE annual-report PDF index.** Each issuer page has a
   `Financials / Annual Reports` section. A second pass should extract
   the per-year PDF URLs and populate `document_url` + `period_end` so
   the existing PDF text-extraction pipeline (CLAUDE.md infra item #1)
   can feed the risk engine.
4. **OpenSanctions overlay.** Tanzanian PEPs are well-covered by
   OpenSanctions; once `risk.engine` wires sanctions screening (infra
   item #8), TZ benefits with zero per-country work.
5. **Non-listed coverage.** ~99% of Tanzanian registered companies are
   not on DSE and are reachable only via BRELA. Realistically this
   needs either (a) a paid aggregator or (b) the BRELA Playwright
   scraper.
