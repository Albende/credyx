# 🇪🇬 Egypt — GLEIF registry + AnnualReports.com filings

## Identifier

- Primary: `COMPANY_NUMBER` — Commercial Registration number (CR), variable
  digits. A 20-character `LEI` is also accepted by `lookup_by_identifier`
  and looked up directly.
- Secondary: `VAT` — Egyptian Tax Authority Tax ID, 9 digits, commonly
  formatted `NNN-NNN-NNN` (e.g. `200-118-815`). No free source indexes it.

## Sources

- **GLEIF** — https://api.gleif.org/api/v1 (free, key-less, JSON:API).
  - Egyptian entities carry the CR number in `entity.registeredAs`
    (registration authority `RA888888` — Ministry of Trade and Industry
    Commercial Registry). Powers both `search_by_name`
    (`filter[fulltext]` + `filter[entity.legalAddress.country]=EG`) and
    `lookup_by_identifier` (`filter[entity.registeredAs]` → LEI → full
    record).
- **AnnualReports.com** — https://www.annualreports.com
  - Hosts the actual filed annual-report PDFs of listed Egyptian issuers
    (e.g. `.../HostedData/AnnualReportArchive/c/OTC_CIBEY_2023.pdf`).
    `fetch_financials` resolves the company name via GLEIF, locates its
    AnnualReports company page, and returns only PDFs that genuinely
    download (verified `application/pdf` / `%PDF-` magic). Coverage is
    issuer-by-issuer; uncovered companies return an empty list (no fabrication).
- **Blocked — not used**: GAFI (gafi.gov.eg) and ETA are sessioned
  captcha-gated web forms; the Egyptian Exchange (egx.com.eg) is behind
  F5/Shape bot defence that FlareSolverr cannot clear (returns the F5
  interstitial, support-ID page). No free national-registry JSON API exists.
- **Auth**: None. No API key required.
- **Rate limit**: None documented. Adapter throttles to 30 req/min.

## Test companies

- Commercial International Bank (CIB) — CR `69826`, LEI
  `213800FIIXJAMEVRIH48`, EGX `COMI`. GLEIF search + CR lookup succeed;
  AnnualReports has 2020–2023 annual-report PDFs.
- Telecom Egypt — LEI `2138002G9HYJY4EDCG86`, EGX `ETEL`. GLEIF search +
  lookup succeed; not on AnnualReports → `fetch_financials` returns `[]`.
- Eastern Company (Eastern Tobacco) — Tax ID `200-001-068`, EGX `EAST`.
- Talaat Moustafa Group — EGX `TMGH`.

## Status

🟢 **Working** — `search_by_name` and `lookup_by_identifier(COMPANY_NUMBER)`
return real GLEIF registry records; `fetch_financials` returns real,
downloadable annual-report PDFs for AnnualReports-covered issuers (verified
live against CIB, CR `69826`).

`lookup_by_identifier(VAT, …)` raises `AdapterNotImplementedError` (surfaces
as HTTP 501) — no free source maps the ETA Tax ID to a company.

## Recommended next steps

1. Widen filing coverage beyond AnnualReports: an EGX scraper is blocked by
   F5/Shape, so evaluate the FRA disclosure portal (non-bank financials
   only) and per-issuer investor-relations PDFs.
2. Wire the PDF text extractor (`packages/risk` / Phase-2 infra) over the
   returned annual-report PDFs to populate `structured_data`.
3. Cross-reference Egyptian entities against OpenSanctions and GLEIF inside
   the risk engine before the LLM step.
