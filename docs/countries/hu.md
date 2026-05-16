# 🇭🇺 Hungary — VIES + e-beszamolo

## Identifiers

- `COMPANY_NUMBER` — Cégjegyzékszám, format `NN-NN-NNNNNN` (2-2-6 digits).
  First pair is the court code, second pair the legal form, then a
  6-digit sequential.
- `VAT` — Hungarian VAT: `HU` + 8-digit törzsszám. The 8-digit törzsszám is
  the first 8 digits of the 11-digit Adószám.

## Sources

### VIES (used)
- URL: `https://ec.europa.eu/taxation_customs/vies/rest-api/ms/HU/vat/{vat}`
- Free public REST. Returns name + address for valid Hungarian VATs.
- No auth. Throttled to 30/min in this adapter.

### e-beszamolo (linked, not yet ingested)
- URL: https://e-beszamolo.im.gov.hu/
- Ministry of Justice annual-report portal. Every Hungarian company files
  balance sheets and annual reports here for **free**, downloadable as PDF
  (and XML for some forms).
- Search and download require a session cookie and CSRF token — needs a
  browser pool, out of MVP scope. The adapter surfaces deep-link
  `source_url`s so users can fetch manually.

### Out of scope (paid)
- `e-cegjegyzek.hu` — full registry extracts behind paid Hungarian eID.
- `opten.hu`, `ceginfo.hu` — paid commercial APIs.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | not implemented | Raises `AdapterNotImplementedError`. e-beszamolo search needs a browser pool. |
| `lookup_by_identifier(VAT)` | works | Via VIES, returns name + address. |
| `lookup_by_identifier(COMPANY_NUMBER)` | partial | Returns Cégjegyzékszám + e-beszamolo deep-link; no registry data without a browser. |
| `fetch_financials` | placeholder | Returns `[]`. Will yield e-beszamolo PDFs once browser-pool infra lands. |

## Rate limits

- Adapter-side throttle: 30 req/min.
- VIES has no documented per-IP limit but soft-blocks abusive callers.
- `Retry-After` is honored by the shared HTTP retry helper.

## Test companies (real)

- OTP Bank Nyrt. — Cégjegyzékszám `01-10-041585`, VAT `HU10537914`.
- MOL Nyrt. — Cégjegyzékszám `01-10-041683`, VAT `HU10625790`.
- Magyar Telekom Nyrt. — Cégjegyzékszám `01-10-041928`.
- Richter Gedeon Nyrt. — Cégjegyzékszám `01-10-040944`.

## Status

🟡 **Degraded** — lookup-by-VAT live via VIES; name search and structured
financials gated on the browser-pool/Playwright work item in the Phase-2
roadmap. No mock data; capabilities that need a browser raise
`AdapterNotImplementedError` or return empty lists with deep-links.

**Recommended next step:** Wire e-beszamolo through `_base/browser.py`
(Playwright) when that infrastructure lands; PDFs are free and the search
URL pattern is stable.
