# 🇪🇹 Ethiopia — MoTI + ESX

## Identifier

- Types: `VAT`, `COMPANY_NUMBER` — both modelled by the 10-digit
  Ethiopian Taxpayer Identification Number (TIN) issued by the
  Ministry of Revenue.
- TIN format: exactly 10 digits, e.g. `0000123456`. Spaces and dashes
  are stripped before validation.
- There is no separate, publicly searchable company-register number
  with a stable free lookup, so the TIN is the canonical identifier in
  scope.

## Sources

- https://moti.gov.et/ — Ministry of Trade and Regional Integration.
  Only partial public information about the commercial register; the
  e-services portal sits behind a session and Fayda national-ID
  authentication.
- https://esxethiopia.com/ — Ethiopian Securities Exchange. Launched
  January 2024 as Ethiopia's first organised securities exchange.
  Initial listings during 2024–2025 — universe is currently very small.
  Issuer disclosure pages are JS-rendered.
- **Auth**:
  - MoTI: e-trade portal requires Fayda eID + session cookies. No
    public REST/JSON API for the commercial register.
  - Ministry of Revenue e-tax (TIN validation) is gated behind Fayda.
  - ESX: public landing pages reachable; per-issuer disclosure pages
    are JavaScript-rendered.
- **Rate limit**: None documented; we self-throttle to 30/min.
- **robots.txt / ToS**: MoTI forbids automated scraping of authenticated
  e-services; ESX permits read-only access to public pages.

## Test companies

- Ethiopian Airlines (state-owned, not publicly listed)
- Commercial Bank of Ethiopia (state-owned)
- Ethio Telecom (state-owned, partial privatisation in progress)
- Awash Bank (private commercial bank)

## Status

🔴 **Blocked / Degraded** — name search and identifier lookup raise
`AdapterNotImplementedError` (MoTI partial + Fayda-gated; no free TIN
validation API). `fetch_financials` returns `[]` until both (a) the PDF
+ browser pipeline lands and (b) ESX disclosure coverage broadens
materially. None of the four flagship test companies above are listed
on ESX today, and they publish annual reports as PDFs on their own
websites only.

**Recommended next steps:**

1. Once ESX listing universe expands and per-issuer disclosure pages
   stabilise, wire them through the planned Playwright pool + PDF
   extraction pipeline.
2. Phase-2: build a Fayda-authenticated MoTI scraping worker (Celery +
   cookie jar) for commercial-register extracts. Requires a registered
   business account inside Ethiopia.
3. Cross-reference Ethiopian entities against OpenSanctions and GLEIF
   (already wired globally) — LEIs exist for the largest banks
   (e.g. CBE, Awash) and surface basic legal-form metadata even when
   the local registry is unreachable.
