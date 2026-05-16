# 🇿🇲 Zambia — PACRA / ZRA / LuSE

## Identifiers

- PACRA Registration Number → `IdentifierType.COMPANY_NUMBER` (primary).
- ZRA TPIN (Taxpayer Identification Number, 10 digits) →
  `IdentifierType.VAT`.

## Sources

- **PACRA** — Patents and Companies Registration Agency
  - https://www.pacra.org.zm/
  - Public name search and certificate purchase exist but sit behind a
    session + CAPTCHA flow; there is no free REST API and no bulk
    download. Document copies are paid (per-page fees in ZMW).
- **ZRA** — Zambia Revenue Authority
  - https://www.zra.org.zm/
  - TPIN lookup is an authenticated taxpayer-portal feature; no public
    machine-readable endpoint.
- **LuSE** — Lusaka Securities Exchange
  - https://www.luse.co.zm/
  - Free annual reports for every listed issuer published as PDFs on the
    per-ticker profile page under `/listed-companies/`.
  - **Auth**: None.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.

## Test companies (real)

- Zambia National Commercial Bank PLC — LuSE ticker `ZANACO`.
- Copperbelt Energy Corporation PLC — LuSE ticker `CEC`.
- Lafarge Zambia PLC — LuSE ticker `LAFA`.
- Stanbic Bank Zambia — private subsidiary of Standard Bank Group;
  filings are consolidated into the parent ZA accounts.

## Status

🟡 **PARTIAL** — health probes LuSE; PACRA/ZRA are blocked behind
session-gated web flows and raise `AdapterNotImplementedError` rather
than fabricating data.

**Capabilities**
- `search_by_name` — not implemented (PACRA scrape required).
- `lookup_by_identifier` — not implemented for either PACRA number or
  TPIN (no free machine-readable endpoint).
- `fetch_financials` — accepts a known LuSE ticker as `company_id` and
  is wired to surface annual reports from the LuSE site; the per-PDF
  crawl is pending so the current contract returns an empty list rather
  than invented filings.

## Known gaps / next steps

1. Playwright-driven PACRA name search and registration-number lookup
   (CAPTCHA solver out of scope until a paid integration is approved).
2. ZRA TPIN validation — likely requires Phase-2 partnership with ZRA
   rather than scraping the taxpayer portal.
3. LuSE annual report crawl: parse `/listed-companies/{slug}` pages,
   collect PDF links per fiscal year, push to the PDF text-extraction
   pipeline, and emit `FinancialFiling(currency="ZMW")` rows.
