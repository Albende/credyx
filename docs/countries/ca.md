# 🇨🇦 Canada — Corporations Canada + SEDAR+

## Identifier

- Type: `COMPANY_NUMBER` (federal Corporation Number, 5–7 digits, often
  displayed with a trailing check digit — `763869-7`). Adapter normalizes by
  stripping the dash.
- Also accepted: `VAT` (Business Number, format `123456789RC0001`) for
  surfacing only — CRA lookup is not free.
- Also accepted: `OTHER` reserved for SEDAR+ profile id (not yet wired).

## Sources

- **Corporations Canada** — https://www.ic.gc.ca/app/scr/cc/CorporationsCanada/
  - Search: `fdrlCrpSrch.html?crpNm=…`
  - Detail: `fdrlCrpDetails.html?corpId=…`
  - **Auth**: No.
  - **Rate limit**: Undocumented; adapter throttles to 60 req/min.
  - **robots.txt / ToS**: Public information, scraping permitted for
    reasonable use. Pages are HTML only — no documented JSON endpoint.
- **SEDAR+** — https://www.sedarplus.ca
  - Public document search for listed-issuer filings (annual + interim
    financial statements, AIF, MD&A).
  - **Auth**: No.
  - **Rate limit**: Undocumented; same 60/min throttle.
- **OpenCorporates** (already wired in `packages/_global`) — used as a
  resilience fallback for name search when the federal source returns
  nothing (e.g. provincially-registered entities).

## Coverage caveat

Corporations Canada covers only **federally** incorporated entities —
roughly one third of Canadian companies. Provincial registries
(ON / QC / BC / AB) are paid per-jurisdiction services and are out of MVP
scope. For provincial-only entities, the adapter falls back to
OpenCorporates' free tier.

## Test companies

- Shopify Inc. (`763869-7`) — federal + SEDAR+ filer.
- Canadian Pacific Kansas City Ltd. (`763028-6`).
- Bombardier Inc. (`285105-9`).
- Royal Bank of Canada — Schedule I bank, federal.

## Status

🟡 **Partial** — federal search + lookup ✅; SEDAR+ financial-filing PDF
URLs ✅ when the document-search endpoint responds. Structured XBRL
extraction from SEDAR+ documents is not yet wired (PDF text-extraction
pipeline applies once available).

**Recommended next steps:**
1. Wire the SEDAR+ XBRL ingestion (Canadian Securities Administrators
   publishes iXBRL alongside PDFs for listed issuers from 2024+).
2. Add provincial adapters in priority order: ON (ServiceOntario),
   QC (Registraire des entreprises), BC (Corporate Online), AB (CORES).
3. CRA Business Number resolution is paid — leave out unless a paid tier
   is approved.
