# 🇯🇴 Jordan — Companies Control Department + Amman Stock Exchange

## Identifiers

- `COMPANY_NUMBER` — CCD company registration number issued by the
  Ministry of Industry, Trade and Supply (MIT) Companies Control
  Department. Variable-length numeric, up to 10 digits.
- `VAT` — 9-digit Tax Reference Number (TRN) issued by the Income and
  Sales Tax Department (ISTD). Used both as the income-tax file number
  and the GST/VAT registration.

The adapter rejects identifier types other than `COMPANY_NUMBER` and
`VAT` with `InvalidIdentifierError`.

## Sources

- Companies Control Department (CCD) — https://www.ccd.gov.jo/.
  Official Jordanian companies register. Public name search is exposed
  through an Arabic-only ASP.NET portal whose XHR endpoints require an
  active session cookie and CSRF token; there is no documented free
  JSON API.
- Ministry of Industry, Trade and Supply — https://www.mit.gov.jo/.
  Parent ministry; portal links into the same CCD search.
- Income and Sales Tax Department (ISTD) — https://www.istd.gov.jo/.
  Hosts the TRN validator. The validator is a form that renders results
  in HTML server-side and is not addressable as a JSON service.
- Amman Stock Exchange (ASE) — https://www.ase.com.jo/.
  Authoritative free source for Jordanian listed-issuer financials.
  Each issuer has a public profile page at
  `https://www.ase.com.jo/en/Company-Profile/{TICKER}` that links to
  audited annual reports as free PDFs.
- **Rate limit**: Not published for any of the above. Adapter throttles
  to 30 req/min.
- **robots.txt / ToS**: ASE annual reports are explicitly published as
  free public disclosures; CCD/ISTD pages are public information pages.

## Test companies

- Arab Bank PLC — ASE ticker `ARBK`.
- Jordan Phosphate Mines Company — ASE ticker `JOPH`.
- Hikma Pharmaceuticals — ASE ticker `HIKM`.
- Jordan Telecom (Orange Jordan) — ASE ticker `JTEL`.

## Status

🟡 **PARTIAL** — financials-only for ASE-listed issuers via public PDFs.
Non-listed companies have no free Jordanian data source today, so
`search_by_name` and `lookup_by_identifier` raise
`AdapterNotImplementedError` rather than fabricate matches.

**Capabilities**

- `search_by_name` — `AdapterNotImplementedError`. CCD/MIT name search
  has no free public JSON contract.
- `lookup_by_identifier` — `AdapterNotImplementedError` for valid
  `COMPANY_NUMBER` and `VAT` (TRN) inputs after format validation;
  `InvalidIdentifierError` for other identifier types or malformed
  values.
- `fetch_financials` — for ASE-listed tickers in the known issuer map,
  returns one `FinancialFiling` per recent fiscal year that points at
  the public ASE company profile (`source_url`). `structured_data` is
  null — the actual PDF parsing is deferred to the cross-cutting PDF
  pipeline described in `CLAUDE.md`. Currency `JOD`. Unknown tickers
  return `[]`.

**Known gaps / next steps**

- ASE issuer enumeration: the listing portal is an Angular SPA with no
  documented JSON catalogue, so the known-ticker map covers MVP test
  companies only. Broader coverage requires the planned Playwright pool
  (`packages/adapters/_base/browser.py`).
- CCD / ISTD: structured access is gated by Arabic-only ASP.NET sessions
  and would require Playwright + session-token replay. Tracked under
  the wider Middle East roadmap in `CLAUDE.md`.
- PDF extraction of ASE annual reports is contingent on the shared
  `pypdf`-based extractor landing.
