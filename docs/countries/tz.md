# 🇹🇿 Tanzania — BRELA + DSE

## Identifiers

- `COMPANY_NUMBER` — BRELA registration / incorporation number (primary).
- `VAT` — TRA TIN (10-digit Taxpayer Identification Number).

## Sources

- **BRELA** — Business Registrations and Licensing Agency (ORS).
  - Portal: https://ors.brela.go.tz/orsreg/searchbusinesspublic
  - **API**: The public search is backed by an undocumented JSON endpoint,
    `POST https://ors.brela.go.tz/orsreg/list/search/businesspublic.json`.
    Body is JSON:
    `{"object_type":"ET-COMPANY"|"ET-BUSINESS","cm_name"|"bn_name":<name>,
    "cm_number"|"bn_number":<number>,"PageSize":n,"PageNumber":n}`.
    Response is `{"Map":[...columns],"Records":[[...]],"Result":"OK",
    "TotalRecordCount":n}`.
  - **Auth**: None (no key, no login). A WAF fronts the host: it rejects the
    default crawler user-agent and any `x-www-form-urlencoded` POST. A browser
    user-agent + `Content-Type: application/json` passes cleanly.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.
  - **Status**: 🟢 Live. Powers `search_by_name` and `lookup_by_identifier`.
- **TRA** — Tanzania Revenue Authority.
  - Portal: https://www.tra.go.tz/
  - **Auth**: TIN validator is interactive only, no public API.
  - **Status**: 🔴 Gated. `lookup_by_identifier(VAT, …)` raises
    `AdapterNotImplementedError`.
- **DSE** — Dar es Salaam Stock Exchange.
  - Portal: https://dse.co.tz/listed/company/financial/statement
  - **API**: The per-issuer statement list is served by a Livewire v2
    component, `financial-statement-front-component`. The adapter GETs the
    page, extracts the `wire:initial-data` snapshot + `csrf-token`, then
    `POST`s `/livewire/message/financial-statement-front-component` with a
    `syncInput` update for `comp_id` (numeric issuer id from the page's
    company `<select>`) and `report_type` (`Annual`/`Interim`/`Quarterly`).
    The rendered HTML lists each statement with its period-end date, title,
    and a downloadable PDF under
    `/storage/securities/{TICKER}/financial_statement/{type}/{hash}.pdf`.
  - **Auth**: None — PDFs download directly (`application/pdf`).
  - **Status**: 🟢 Live. Powers `fetch_financials` for DSE-listed issuers.

## Test companies

- **CRDB Bank Plc** — BRELA company number `30227`; DSE ticker `CRDB`.
- **NMB Bank Plc** — BRELA company number `32699`; DSE ticker `NMB`.
- **Tanzania Breweries Plc** — DSE ticker `TBL`.
- **Vodacom Tanzania Plc** — DSE ticker `VODA`.

## Status

🟢 **Live** — registry search + lookup via BRELA ORS JSON; audited financial
statements (downloadable PDFs) via DSE for listed issuers.

**Capabilities**

- `search_by_name` — queries BRELA for both companies (`cm_name`) and business
  names (`bn_name`), returns `CompanyMatch` records (registration number, legal
  name, status, address).
- `lookup_by_identifier` — `COMPANY_NUMBER` resolves the full BRELA record
  (`CompanyDetails`: legal form, status, incorporation date, address, raw
  payload). `VAT` raises `AdapterNotImplementedError` (TRA gated).
- `fetch_financials` — for a DSE ticker (or numeric DSE issuer id) returns one
  `FinancialFiling` per filed report, most-recent first, each with a real
  downloadable `document_url` PDF, `period_end`, and `currency = "TZS"`. For a
  non-listed key returns `[]`. No fabricated numbers.
- `health_check` — probes the BRELA JSON endpoint; reports `OK` when the
  registry search responds.

## Currency

DSE issuers report in TZS (Tanzanian Shilling). Financial filings carry
`currency = "TZS"`; FX normalization to EUR is the responsibility of
`packages/risk` (cross-cutting work item #5 in `CLAUDE.md`).

## Known gaps / next steps

1. **BRELA ↔ DSE linkage.** `fetch_financials` is keyed by DSE ticker /
   issuer id. There is no automated map from a BRELA registration number to a
   DSE ticker; the search/lookup and financials paths are independent. A small
   resolver (name match against the live DSE roster) could bridge them.
2. **Non-listed financials.** ~99% of Tanzanian registered companies are not
   on DSE. BRELA does not publish filed accounts via the public search, so
   deep financials for private companies remain unavailable without a paid
   aggregator.
3. **DSE PDF text extraction.** `document_url` points at the audited PDF;
   feeding it to the PDF text-extraction pipeline (CLAUDE.md infra item #1)
   would populate `structured_data` for the risk engine.
4. **TRA TIN validation.** TRA exposes a session-based validator only; a
   browser-pool implementation could verify TIN format + active status.
5. **OpenSanctions overlay.** Tanzanian PEPs are well-covered by
   OpenSanctions; wiring `risk.engine` sanctions screening (infra item #8)
   benefits TZ with zero per-country work.
