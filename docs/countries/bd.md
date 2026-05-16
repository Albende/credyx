# 🇧🇩 Bangladesh — RJSC + NBR + DSE

## Identifier

- Primary: `Registration Number` (RJSC) — variable-length numeric ID,
  typically 4-7 digits, assigned by the Office of the Registrar of Joint
  Stock Companies and Firms. Mapped to `IdentifierType.COMPANY_NUMBER`.
- Secondary: `BIN` (Business Identification Number, also called e-BIN /
  VAT registration) — 9 digits (legacy) or 13 digits (current NBR
  format). Mapped to `IdentifierType.VAT`.
- `TIN` (Taxpayer Identification Number) — 12 digits, NBR. Not separately
  queryable for free; not exposed as a distinct adapter input.
- For DSE-listed companies, the trading symbol (e.g. `GP`, `BRACBANK`,
  `SQURPHARMA`) is accepted as a `COMPANY_NUMBER` short-circuit and
  routed to the DSE path. Stored on results as `IdentifierType.OTHER`
  with label `DSE Symbol`.

## Sources

- **RJSC public search** (free, HTML scrape, non-standard port 7781):
  http://www.roc.gov.bd:7781/psp/searchEntities.action
- **NBR BIN / e-TIN portal** (partial public HTML, CAPTCHA + login on
  detail): https://nbr.gov.bd/
- **DSE (Dhaka Stock Exchange) Data Portal** (free, annual reports for
  listed companies): https://www.dsebd.org/
- **Auth**: None used. RJSC detail and NBR detail are CAPTCHA / session
  gated; we deliberately do not drive those flows.
- **Rate limit**: We self-throttle to 30 req/min. RJSC is brittle under
  load and the port-7781 service is regularly geofenced; respect 5xx
  with backoff (already handled by `get_with_retry`).
- **robots.txt / ToS**: DSE permits non-commercial use with attribution.
  RJSC has no public ToS for the search route; we treat it as
  permission-by-default while obeying rate limits.

## Test companies

- Grameenphone Ltd. — DSE symbol `GP`
- BRAC Bank Limited — DSE symbol `BRACBANK`
- Square Pharmaceuticals Limited — DSE symbol `SQURPHARMA`
- Beximco Pharmaceuticals Limited — DSE symbol `BXPHARMA`

## Status

🟡 **Partial** — DSE-listed lookup ✅ (8 companies hard-listed); RJSC
name search ❌ (CAPTCHA / port 7781 brittle); RJSC detail by
Registration Number ❌ (session-gated); NBR BIN lookup ❌
(CAPTCHA + login gated); listed financials ⚠️ (navigation pointers
only, no structured numbers).

### What works

- `search_by_name(name)` — returns DSE-listed companies whose name or
  trading symbol contains the query, with `source_url` pointing at
  `dsebd.org/displayCompany.php?name={SYMBOL}`. Returns `[]` for empty
  input; raises `AdapterNotImplementedError` (501) when there is no
  listed match and the RJSC name-search route is needed.
- `lookup_by_identifier(COMPANY_NUMBER, <DSE_SYMBOL>)` — returns a
  `CompanyDetails` populated from the small in-adapter `DSE_LISTED`
  table (name, sector, currency=BDT, source_url). No fabricated
  registry fields.
- `fetch_financials(<DSE_SYMBOL>)` — returns one `FinancialFiling`
  navigation pointer per recent fiscal year (`structured_data=None`,
  `source_url` set). No fabricated numbers.
- `health_check()` — probes dsebd.org; surfaces the partial-coverage
  notes.

### What does not work in MVP

- **RJSC name search** (`search_by_name` for non-listed): the public
  endpoint runs on a non-standard port (7781), is regularly geofenced
  outside Bangladesh, and the detail click-through is CAPTCHA + session
  gated. We raise `AdapterNotImplementedError` rather than scrape an
  unreliable front-end and risk silent data drift.
- **RJSC Registration Number lookup** (`lookup_by_identifier` numeric):
  the per-company page is hidden behind the eServices authenticated
  session. We honestly raise 501.
- **NBR BIN lookup**: NBR's online BIN / e-TIN inquiry is CAPTCHA +
  login gated. No free programmatic path; raises 501.
- **Structured listed financials**: DSE publishes annual reports as
  per-year PDFs but the index is rendered client-side from a session-
  bound query. We return navigation pointers (one per FY) and let the
  PDF text extraction pipeline (Phase-2 cross-cutting work) ingest the
  document once a URL is reached.
- **Unlisted financials**: RJSC document downloads are paid
  per-document — out of scope for the free MVP.

## Recommended next steps

1. Build a nightly ingest of the **DSE listed-company master list**
   (HTML scrape of `https://www.dsebd.org/by_industrylisting.php`) to
   replace the hard-coded `DSE_LISTED` map and pick up new listings
   automatically.
2. Add a **PDF extraction job** that walks each DSE company page,
   downloads the latest annual report PDF, runs `pypdf` text
   extraction, and stores the text on `FinancialFiling.structured_data`
   for the LLM. This depends on the cross-cutting PDF pipeline from
   `CLAUDE.md`.
3. Phase-2: license RJSC paid bulk data (CSV) from the Ministry of
   Commerce, if/when an official feed is published, to enable real
   `search_by_name` and unlisted `lookup_by_identifier`.
4. Phase-2: integrate **Bangladesh Bank** open data
   (https://www.bb.org.bd/) for FX, banking-sector aggregates, and
   sanctions/PEP-equivalent watchlists once the cross-cutting
   sanctions wiring lands.
