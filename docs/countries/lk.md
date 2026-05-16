# 🇱🇰 Sri Lanka — CSE + DRC (eROC) + IRD

## Identifier

- Primary: DRC Company Registration Number, format `PV`/`PB`/`PQ`/`PVS`/`N(V)` + up to 9 digits (e.g. `PV 312`).
- Working primary for listed issuers: **CSE ticker** (e.g. `JKH`, `DIAL`) → internal symbol `JKH.N0000`.
- Secondary: IRD TIN (9–10 digits) — validation requires browser session.

## Sources

### CSE (Colombo Stock Exchange) — primary live source
- Base: https://www.cse.lk
- Undocumented JSON POST endpoints used by the public site, both `application/x-www-form-urlencoded`:
  - `POST /api/companyInfoSummery` — symbol → issuer snapshot (name, issue date, par value, prices).
  - `POST /api/companyInfoFinancials` — symbol → list of filed annual report PDFs (`infoAnnualData[].path`, `manualDate`).
- PDFs are served from `https://cdn.cse.lk/{path}`.
- **Auth**: None.
- **Rate limit**: Undocumented; we self-throttle to 30 req/min.
- **ToS / robots.txt**: Public site, no machine-readable license; the endpoints are the ones the browser already calls, so this is "respectful client" usage.

### DRC (Department of Registrar of Companies) — eROC
- https://eroc.drc.gov.lk/ — JavaScript SPA with no documented JSON API.
  Name search and detail view require a browser session; not feasible
  without Playwright.
- Bulk data not published.

### IRD (Inland Revenue Department)
- https://www.ird.gov.lk/ — TIN validator is a partial-public web form,
  not a machine-readable endpoint.

## Test companies (CSE-listed, used in the integration suite)

- John Keells Holdings PLC — ticker `JKH` (symbol `JKH.N0000`).
- Dialog Axiata PLC — ticker `DIAL`.
- Commercial Bank of Ceylon PLC — ticker `COMB`.
- Sri Lanka Telecom PLC — ticker `SLTL`.

## Status

🟡 **Partial** — CSE-listed issuer search, lookup and annual-report PDF
links all work via the CSE JSON endpoints. DRC eROC and IRD TIN lookups
raise `AdapterNotImplementedError` because neither source publishes a
machine-readable API and both require a browser session.

**Recommended next step:** Once `packages/adapters/_base/browser.py`
(Playwright pool) lands as part of the cross-cutting infra, add a DRC
eROC scraper to extend name search and lookup to private companies
(by far the larger universe). For listed PLCs, plug `pypdf` into the
existing `fetch_financials` output so the LLM context can include
balance-sheet text excerpts.
