# 🇵🇰 Pakistan — PSX Data Portal (SECP / FBR gated)

## Identifier

- Primary: `Incorporation Number` (SECP) — variable-length numeric ID,
  typically 7 digits, often zero-padded (e.g. `0012345`). Mapped to
  `IdentifierType.COMPANY_NUMBER`. A **PSX trading symbol** (short alpha
  token, e.g. `HBL`, `ENGRO`, `PPL`, `LUCK`) is accepted on the same
  identifier slot and is the working lookup key for listed companies.
- Secondary: `NTN` (National Tax Number, FBR) — 7- or 8-digit numeric
  ID, optionally suffixed with `-<check>`. Mapped to
  `IdentifierType.VAT`.

## Sources

- **PSX Data Portal symbol directory** — free JSON, no key, ~1,080 listed
  symbols with name + sector: https://dps.psx.com.pk/symbols
- **PSX Data Portal company page** — free HTML, no key, per company:
  https://dps.psx.com.pk/company/{SYMBOL} — carries the company profile
  (business description, key people), an annual + quarterly financials
  table with filed figures (000's PKR, EPS in PKR), and an announcements
  table linking the real annual-report / quarterly-report PDFs the
  company transmitted to the exchange.
- **SECP eServices** (unlisted name search / Incorporation Number
  lookup) — ASP.NET ViewState + CAPTCHA gated, no free programmatic path:
  https://www.secp.gov.pk/
- **FBR Online Verification** (NTN inquiry) — CAPTCHA gated:
  https://e.fbr.gov.pk/
- **Auth**: None. The PSX Data Portal is fully open (no key, no login).
- **Rate limit**: self-throttle to 30 req/min.
- **robots.txt / ToS**: PSX permits non-commercial use of annual reports
  with attribution.

## Test companies

- Habib Bank Limited — PSX `HBL`
- Engro Corporation Limited — PSX `ENGRO`
- Pakistan Petroleum Limited — PSX `PPL`
- Lucky Cement Limited — PSX `LUCK`

## Status

🟢 **Live** for PSX-listed companies (the entities that matter for credit
work): name search ✅, symbol lookup ✅, filed financials ✅. Unlisted
SECP Incorporation Number lookup ❌ and FBR NTN inquiry ❌ remain
CAPTCHA/ViewState gated and return `AdapterNotImplementedError` (501).

### What works

- `search_by_name` — queries the live PSX symbol directory
  (`/symbols`) and returns every listed company (or debt/GEM instrument)
  whose name or symbol matches. Real names, PSX symbols, source URLs.
  Raises `AdapterNotImplementedError` when nothing matches.
- `lookup_by_identifier(COMPANY_NUMBER, <PSX symbol>)` — scrapes the live
  company page and returns `CompanyDetails` (name, sector, legal form,
  business description, key people as directors, PSX source URL).
- `fetch_financials(<PSX symbol>, years=N)` — parses the company page's
  annual financials table into one `FinancialFiling` per filed year
  (`type=annual_report`, `currency=PKR`, `structured_data.metrics` with
  the filed figures) and attaches the real annual-report PDF
  `document_url` for years where the exchange still lists the
  transmission announcement. No fabricated numbers — every figure and PDF
  URL is read from the company's own PSX page.

### What does not work in MVP

- **`search_by_name` / lookup for unlisted companies**: SECP eServices is
  session-bound and gated by CAPTCHA + ASP.NET ViewState. Raises
  `AdapterNotImplementedError` (→ 501) per the no-mock-data rule.
- **`lookup_by_identifier(COMPANY_NUMBER, <numeric Incorporation Number>)`**:
  SECP per-company detail pages require an authenticated eServices
  session; raised as 501.
- **`lookup_by_identifier(VAT, <NTN>)`**: FBR Online Verification requires
  CAPTCHA + ViewState; raised as 501.

## Recommended next steps

1. Stand up the Playwright browser pool
   (`packages/adapters/_base/browser.py`) to drive the SECP eServices
   CAPTCHA + ViewState flow for unlisted name search and Incorporation
   Number lookup.
2. Ingest the SECP "Active Companies" list (when published) into Postgres
   nightly so unlisted `search_by_name` can serve from a local index.
3. Wire the annual-report `document_url` PDFs into the PDF text
   extraction pipeline for the LLM context (Pakistani filings follow
   IAS/IFRS, so a generic IFRS parser fits).
4. Phase-2 paid option: PACRA / VIS Credit Rating Company for credit
   ratings on rated entities.
5. OpenSanctions screen for Pakistani PEPs / FATF-listed entities is
   available via `packages/adapters/_global/opensanctions.py` — wire into
   `risk.engine` before the LLM step.
