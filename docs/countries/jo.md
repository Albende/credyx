# 🇯🇴 Jordan — Amman Stock Exchange (ASE)

## Identifiers

- `OTHER` — ASE ticker symbol (e.g. `JOPH`, `ARBK`). Primary identifier;
  the stable key used across search, lookup, and financials.
- `COMPANY_NUMBER` — ASE numeric security code (e.g. `141018`). Accepted
  by `lookup_by_identifier` as a secondary key.

The adapter rejects identifier types other than `OTHER` and
`COMPANY_NUMBER` with `InvalidIdentifierError`.

## Sources

- Amman Stock Exchange (ASE) — https://www.exchange.jo/ (formerly
  `www.ase.com.jo`). The authoritative **free** structured source for
  Jordanian listed companies. No API key, no session token required.
  - **Listed-issuer directory** —
    `/en/products-services/securties-types/shares`. A public HTML table
    of every listed share issuer with English + Arabic long/short name,
    ASE ticker symbol, numeric security code, paid-up capital, and market
    segment. ~155 issuers. Backs `search_by_name` and
    `lookup_by_identifier`.
  - **Disclosure filings** — `/en/disclosures?symbol={TICKER}&category_id=1`.
    `category_id=1` is "Annual Financial Report". Each row exposes a
    downloadable audited-statements document (PDF, ZIP, or XLS/XLSX) at
    `/en/{download|zip|excel}/disclosure/{id}`. Backs `fetch_financials`.
- Companies Control Department (CCD) — https://www.ccd.gov.jo/. Official
  Jordanian companies register. **Not usable**: Arabic-only ASP.NET
  WebForms portal, event-validation-gated XHR, no free JSON/REST API and
  no bulk export (confirmed live, 2026-07). Non-listed companies
  therefore have no free structured Jordanian source today.
- Income and Sales Tax Department (ISTD) — https://www.istd.gov.jo/.
  TRN validator is a client-rendered form with no JSON contract.
- **Rate limit**: Not published. Adapter throttles to 30 req/min.
- **robots.txt / ToS**: ASE disclosures are explicitly published as free
  public disclosures; the shares directory is a public information page.

## Test companies

- Jordan Phosphate Mines — ASE ticker `JOPH`, security code `141018`.
- Arab Bank — ASE ticker `ARBK`, security code `113023`.
- Jordan Telecom (Orange Jordan) — ASE ticker `JTEL`, security code `131206`.
- Jordan Islamic Bank — ASE ticker `JOIB`, security code `111001`.

(Note: Hikma Pharmaceuticals is **not** ASE-listed — it trades on the
London Stock Exchange and Nasdaq Dubai — so it is not a JO test company.)

## Status

🟢 **LIVE** — search, lookup, and financials all return real data for
ASE-listed issuers, key-free, from exchange.jo.

**Capabilities**

- `search_by_name` — case-insensitive substring match over the ASE
  listed-issuer directory (long + short English names). Returns
  `CompanyMatch` records keyed by ticker symbol, each carrying the
  ticker (`OTHER`) and security code (`COMPANY_NUMBER`) identifiers.
  Non-listed companies simply return no match.
- `lookup_by_identifier` — resolves an ASE ticker (`OTHER`) or security
  code (`COMPANY_NUMBER`) to a `CompanyDetails` with name, paid-up
  capital (JOD), market segment, and identifiers. `None` if not listed;
  `InvalidIdentifierError` for other identifier types or malformed input.
- `fetch_financials` — for a listed ticker (or security code), fetches
  the issuer's "Annual Financial Report" disclosures and returns one
  `FinancialFiling` per recent fiscal year (most recent first, de-duped),
  each with a live, verified `document_url` to the audited-statements
  file (PDF/ZIP/XLS) and a `source_url` to the filtered disclosures page.
  `year` is the fiscal year (disclosure publication year − 1, the ASE
  convention for post-year-end audited annual reports). `structured_data`
  is null — parsing the ZIP/PDF/XLS is deferred to the cross-cutting
  document-extraction pipeline described in `CLAUDE.md`. Currency `JOD`.
  Unknown/non-listed identifiers return `[]`.

**Known gaps / next steps**

- Coverage is the ASE-listed equity universe (~155 issuers). Private /
  non-listed Jordanian companies need the gated CCD register — tracked
  under the wider Middle East roadmap in `CLAUDE.md`.
- `structured_data` extraction of the downloaded annual-report
  ZIP/PDF/XLS is contingent on the shared document-extraction pipeline.
