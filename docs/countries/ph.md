# 🇵🇭 Philippines — PSE Edge

## Why not the SEC registry

The SEC's former public viewer `iview.sec.gov.ph` was retired and no longer
resolves (DNS `NXDOMAIN`). The SEC's replacement portals — eSPARC
(`esparc.sec.gov.ph`) and eSEARCH (`secexpress.ph`) — sit behind a bot wall
and their terms explicitly forbid automated/bulk scraping, and the SEC API
Marketplace (`portal.sec.gov.ph`) is subscription-gated. There is therefore
**no free, no-auth, machine-readable SEC company API** as of 2026.

The one free, no-key, machine-readable Philippine source that returns real
company data — including **downloadable audited financial statements** — is
**PSE Edge**, the Philippine Stock Exchange disclosure portal. Coverage is
consequently **PSE-listed companies** (the large-cap universe). For unlisted
companies there is no free official machine-readable source, so
`search_by_name` returns only listed matches and never fabricates a record.

## Identifier

- Primary: `COMPANY_NUMBER` — carries the **PSE ticker symbol** (e.g. `SM`,
  `AC`, `BDO`, `JFC`). This is the stable public handle PSE Edge uses to
  address a company; the SEC Registration Number is not exposed by any free
  machine-readable source. Normalization: strip whitespace, drop an optional
  `PSE:` prefix, uppercase, require `[A-Z][A-Z0-9]{0,9}`.

## Sources — PSE Edge (`https://edge.pse.com.ph`, no auth)

### Search — autocomplete JSON

- `GET /autoComplete/searchCompanyNameSymbol.ax?term={query}` →
  `[{cmpyId, cmpyNm, symbol, etfYn}, …]`. Backs `search_by_name`; each row
  becomes a `CompanyMatch` keyed by `symbol`.

### Lookup — company profile

- `GET /companyInformation/form.do?cmpy_id={id}` → the company profile page
  (a clean two-column table). We parse **Sector / Subsector, Incorporation
  Date, Business Address, External Auditor, Website, Telephone, Fiscal
  Year**. The symbol is resolved to `cmpyId` via the autocomplete endpoint
  first. Backs `lookup_by_identifier`.

### Financials — filed annual reports (SEC Form 17-A)

- `POST /companyDisclosures/search.ax` with
  `keyword={cmpyId}&tmplNm=Annual Report&sortType=date&dateSortType=DESC` →
  an HTML table of the company's filed annual reports. Each row's
  `openPopup('{edge_no}')` links to the disclosure viewer.
- `GET /openDiscViewer.do?edge_no={edge_no}` → the disclosure viewer, whose
  `<option>` attachments are the real **SEC Form 17-A PDF** plus the audited
  financial statements. We pick the 17-A / Annual Report attachment.
- The attachment downloads directly via
  `GET /downloadFile.do?file_id={file_id}` (verified: returns
  `application/octet-stream`, `%PDF` payload, multi-MB). This is the
  `document_url` on each `FinancialFiling`.
- Fiscal year is read from the attachment filename (`… as of 31 December
  YYYY`, or a leading `YYYY`), falling back to `filed_year − 1` (17-A is due
  105 days after a 12/31 fiscal-year end). Filings are de-duplicated by
  fiscal year, keeping the most recent (handles amendments).
- We emit **filing metadata only** (year, type, currency, period end,
  source URL, downloadable PDF URL) — no parsed numbers. A downstream PDF
  pipeline turns the 17-A into `structured_data`.

## Test companies

- SM Investments Corporation — PSE `SM` (cmpyId 599)
- Ayala Corporation — PSE `AC` (cmpyId 57)
- BDO Unibank, Inc. — PSE `BDO`
- Jollibee Foods Corporation — PSE `JFC` (cmpyId 86)

## Status

✅ **Live** — search + lookup + financials all return real data via PSE
Edge, no API key. Financials include downloadable SEC Form 17-A PDFs for the
specific company.
🟡 **Scope** — PSE-listed companies only; unlisted firms return `[]` (no free
official source). A paid SEC integration would be needed for unlisted
coverage and is out of scope per the no-paid-APIs rule.

**Recommended next steps:**

1. Plug the filed 17-A / AFS PDFs into the project-wide PDF/iXBRL pipeline so
   `document_url` becomes `structured_data` (ratios) for the risk engine.
2. Cache the autocomplete symbol → `cmpyId` mapping to cut one request per
   lookup/financials call.
