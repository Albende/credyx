# 🇺🇿 Uzbekistan — stat.uz / soliq.uz / UZSE (liveness only)

## Identifier

- Type: `VAT` (primary), also accepted as `COMPANY_NUMBER`.
- Format: **INN** — 9 digits assigned by the State Tax Committee
  ("STIR" in Uzbek, "ИНН" in Russian). Sometimes written with a `UZ`
  prefix; the adapter strips it. Same number serves as the VAT
  registration ID and the corporate tax ID.

## Sources

- https://stat.uz/ — State Statistics Committee. Publishes industry
  aggregates and hosts a public legal-entity directory, but the search
  is session-bound HTML; no documented JSON / REST contract.
- https://soliq.uz/ — State Tax Committee. Provides a public STIR
  (INN) check form, but the response is rendered through a logged-in
  portal flow and is not a stable scrape target.
- https://uzse.uz/ — Republican Stock Exchange "Tashkent". Hosts
  disclosures and annual reports for the ~120 listed issuers. Used
  here only as the **liveness probe** — disclosure URLs are
  session/page-numbered, not a clean feed.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — government and exchange
  sites publish no budget.

## Test companies

- Uzbekneftegaz JSC (oil & gas, listed on UZSE)
- Kapitalbank (commercial bank)
- Hamkorbank (commercial bank, listed on UZSE)
- Uzbekistan Airways (national flag carrier)

## Status

🟡 **Stub-plus — liveness probe only.**

| Capability  | Status                                  |
|-------------|-----------------------------------------|
| Name search | ❌ Not implemented (no public endpoint) |
| INN lookup  | ❌ Not implemented (no public JSON)     |
| Financials  | ❌ Returns `[]` — never invented        |
| Health      | ✅ Probes uzse.uz                       |

## Limitations

- **No public name search.** Neither stat.uz nor soliq.uz exposes a
  documented search endpoint, and UZSE only covers ~120 listed
  issuers. `search_by_name` raises `AdapterNotImplementedError`.
- **No public INN → structured-record lookup.** soliq.uz's STIR check
  requires a session/captcha flow we will not scrape blindly.
  `lookup_by_identifier` validates the 9-digit INN shape (returning
  `InvalidIdentifierError` early for bad input) then raises
  `AdapterNotImplementedError`.
- **No filings.** `fetch_financials` validates the INN shape and
  returns an empty list. Per the no-mock-data rule, we never fabricate
  filings; a Phase-2 UZSE scraper can populate listed-issuer reports
  here without changing the interface.

## Recommended next steps

1. **UZSE listed-issuer scraper.** Parse the disclosure index for each
   listed company, extract annual-report PDF URLs, and surface them
   through `fetch_financials`. Around 120 issuers — a one-day job once
   a Playwright pool exists.
2. **soliq.uz STIR check.** Investigate whether the State Tax
   Committee exposes a paginated public mirror with stable URLs (some
   regional tax offices publish CSV dumps).
3. **OpenCorporates bridge.** OpenCorporates' free tier carries
   partial UZ data; could be wired in for fuzzy name → INN resolution
   without violating the no-paid-API rule.
4. **e-Imzo integration.** Most authoritative Uzbek datasets require
   an e-Imzo electronic signature for access — out of scope for the
   free MVP but worth tracking.
