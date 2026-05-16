# Malta — MBR + VIES + MSE

## Identifiers

- `COMPANY_NUMBER` — "C" + 1–7 digits (e.g. `C2833`, `C 22334`).
- `VAT` — `MT` + 8 digits.

## Sources

- **MBR (Malta Business Registry)** — https://registry.mbr.mt/ROC/index.jsp
  - Free public name search and per-company HTML detail pages.
  - Full registered extracts and filed accounts are paid per document.
  - No documented rate limit; adapter throttles to 30 req/min.
- **VIES** — https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  - Free SOAP endpoint, validates MT VAT and returns registered name + address.
- **Malta Stock Exchange** — https://www.borzamalta.com.mt/
  - Free annual reports (PDF) on each listed issuer's page. Only useful for
    MSE-listed plcs; everyone else has no free filings.

## Test companies

| Name | Company Number |
|------|----------------|
| Bank of Valletta plc | C 2833 |
| HSBC Bank Malta plc | C 3177 |
| GO plc (telecom) | C 22334 |
| International Hotel Investments plc | C 26136 |

## Status

Wired. Search via MBR HTML scrape, lookup via VIES (VAT) or MBR (company
number), financials via Malta Stock Exchange issuer pages for the four
listed majors above. Non-listed MT companies return `[]` for financials —
their filings sit behind MBR's per-document paywall.

**Phase-2 upgrade path:** Pay MBR for online extract access, then parse
the company information statement + annual return for structured filings.
