# 🇧🇴 Bolivia — SEPREC + Impuestos Nacionales + BBV

## Identifiers

- `VAT` → **NIT** (Número de Identificación Tributaria), 7–11 digits, issued by
  Servicio de Impuestos Nacionales.
- `COMPANY_NUMBER` → **Matrícula de Comercio**, issued by SEPREC.

## Sources

- **SEPREC** (Servicio Plurinacional de Registro de Comercio):
  https://www.seprec.gob.bo/ — public Matrícula de Comercio consultation.
  Session-based JS web app, CAPTCHA-protected, no free REST API.
- **Impuestos Nacionales**: https://impuestos.gob.bo/ — NIT validator behind a
  CAPTCHA / session form. No documented public JSON endpoint.
- **BBV** (Bolsa Boliviana de Valores): https://www.bbv.com.bo/ — free annual
  reports / "Memorias Anuales" for listed issuers. No per-issuer JSON feed; the
  adapter surfaces the public "Emisores" directory as a discovery URL.

## Auth, rate limits, ToS

- No API key.
- No documented rate limits; adapter throttles itself to 30 req/min.
- BBV homepage allows polite crawling; SEPREC and Impuestos forbid scraping in
  practice via CAPTCHAs and short-lived sessions.

## Test companies (real)

- **YPFB** (Yacimientos Petrolíferos Fiscales Bolivianos) — state-owned;
  NIT 1020601022.
- **Banco Mercantil Santa Cruz** — BBV-listed.
- **Telecel S.A.** (Tigo Bolivia) — large private telecom.
- **BISA Seguros y Reaseguros** — partial public info via Impuestos.

## Status

🟡 **Partial** — `fetch_financials` returns BBV discovery URLs for listed
issuers; `search_by_name` and `lookup_by_identifier` raise
`AdapterNotImplementedError` (HTTP 501). No mock data is ever returned.

**Recommended next step:** Wire a Playwright-based scraper for SEPREC /
Impuestos Nacionales once the shared browser pool (`packages/adapters/_base/
browser.py`) and CAPTCHA-handling infrastructure land in Phase 2. For BBV,
parse the "Emisores" directory once per day and cache the NIT → issuer-code
mapping so `fetch_financials` can return actual PDF links instead of the
directory pointer.
