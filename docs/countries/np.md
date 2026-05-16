# 🇳🇵 Nepal — OCR + IRD + NEPSE

## Identifiers

- `COMPANY_NUMBER` — OCR (Office of the Company Registrar) Company
  Registration Number. Variable-length numeric (typically 4-7 digits),
  occasionally hyphenated/slashed in marketing copy. Normalized to bare
  digits.
- `VAT` — PAN (Permanent Account Number), 9 digits, issued by the IRD
  (Inland Revenue Department). The same number functions as the VAT
  registration ID for VAT-registered taxpayers.

## Sources

### NEPSE — Nepal Stock Exchange (used)
- URL: `https://www.nepalstock.com/`
- Free, public site. Per-company landing page at
  `https://www.nepalstock.com/company/detail/{SYMBOL}` lists annual
  reports as PDF downloads (rendered by JS but page itself is reachable).
- No auth. The adapter surfaces deep-link `source_url`s per recent FY
  for the curated list of listed companies; structured numbers will be
  populated once PDF text extraction (`packages/risk` pipeline / Phase-2
  PDF infrastructure) is wired.

### OCR — Office of the Company Registrar (linked, not ingested)
- URL: `https://ocr.gov.np/`
- Public name-search form, but the result table and every detail page
  are JavaScript-rendered behind a session cookie. Cannot be driven by
  pure httpx — needs the Playwright browser pool from the Phase-2
  cross-cutting infra work item.
- The adapter raises `AdapterNotImplementedError` for OCR-only lookups
  rather than fabricating data.

### IRD — Inland Revenue Department PAN validator (linked, not ingested)
- URL: `https://ird.gov.np/`
- Free public form but CAPTCHA-gated; no machine-friendly endpoint. PAN
  lookups raise `AdapterNotImplementedError` per the no-mock-data rule.

### Out of scope (paid / fragmented)
- Commercial Nepali credit-rating reports (ICRA Nepal, CARE Ratings
  Nepal) — paid subscriptions only.
- Provincial / department-level filings (Department of Industry for
  industrial registrations) — fragmented and largely offline.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | partial | Returns NEPSE-listed matches; raises `AdapterNotImplementedError` for unknown names (OCR search needs a browser pool). |
| `lookup_by_identifier(COMPANY_NUMBER)` with NEPSE symbol | works | Returns curated `CompanyDetails` + NEPSE source URL. |
| `lookup_by_identifier(COMPANY_NUMBER)` with OCR number | not implemented | Raises `AdapterNotImplementedError`. OCR detail pages are session/JS-gated. |
| `lookup_by_identifier(VAT)` | not implemented | Raises `AdapterNotImplementedError`. IRD PAN validator is CAPTCHA-gated. |
| `fetch_financials` | partial | Returns one `FinancialFiling` deep-link per recent FY for NEPSE-listed companies; `[]` for unlisted. No fabricated numbers. |

## Rate limits

- Adapter-side throttle: 30 req/min.
- NEPSE and OCR publish no documented per-IP limits but rate-limit
  abusive callers. `Retry-After` is honored by the shared HTTP retry
  helper.

## Test companies (real)

- Nabil Bank Limited — NEPSE symbol `NABIL`.
- Nepal Telecom (Nepal Doorsanchar Company Ltd.) — NEPSE symbol `NTC`.
- Nepal Investment Mega Bank Limited — NEPSE symbol `NIMB`.
- Standard Chartered Bank Nepal Limited — NEPSE symbol `SCB`.

## Status

🟡 **Degraded** — NEPSE listed-company lookups and deep-link filings work
today; OCR/IRD flows raise `AdapterNotImplementedError` because both are
session/CAPTCHA-gated and the codebase has no browser pool yet. No mock
data anywhere.

**Recommended next step:** When the Playwright browser pool
(`packages/adapters/_base/browser.py`, Phase-2 cross-cutting work) lands,
drive ocr.gov.np search and ird.gov.np PAN validation through it.
Independently, wire the PDF text extraction pipeline so the NEPSE
annual-report PDFs flow into `pdf_text_excerpts` and the risk engine
gets real financial context for listed Nepali companies.
