# 🇲🇬 Madagascar — EDBM

## Identifier

- Types: `VAT` (NIF — Numéro d'Identification Fiscale, issued by DGI),
  `COMPANY_NUMBER` (STAT — Numéro Statistique, issued by INSTAT).
- NIF format: numeric, typically 7–12 digits.
- STAT format: 10–20 alphanumeric characters combining sector, region
  and sequence (e.g. `61201112020100123`).

## Sources

- https://edbm.mg/ — Economic Development Board of Madagascar (the
  one-stop-shop for incorporation and the only partly-public company
  index).
- **No stock exchange** in Madagascar — no free listed-filings fallback.
- **Auth**: EDBM portal is JS-rendered with no documented JSON API;
  structured extracts and certified documents are paid and typically
  issued in-person at the EDBM counter.
- **Rate limit**: None documented; we self-throttle to 20/min.
- **robots.txt / ToS**: EDBM does not publish a permissive automation
  policy; treat the site as scrape-grey and gate behind a Playwright
  pool with a low rate.

## Test companies

- Telma Madagascar (NIF/STAT not publicly indexed in a free API).
- Air Madagascar.
- Ambatovy Minerals S.A.

(Identifiers cannot be confirmed without an EDBM session — included
for name reference only.)

## Status

🔴 **Blocked / Degraded** — name search and identifier lookup raise
`AdapterNotImplementedError` (EDBM is JS-rendered and gated; structured
DGI/INSTAT lookups are not publicly exposed). `fetch_financials`
returns `[]` because there is no free filings source at all (no stock
exchange, no published balance sheets via EDBM).

**Recommended next steps:**

1. Wire EDBM name search through the planned Playwright pool once the
   browser infrastructure (`packages/adapters/_base/browser.py`) is
   available.
2. Phase-2: investigate paid access to the EDBM commercial register
   extracts (per-document fees, requires a Malagasy bank-card payment
   rail).
3. Without a stock exchange or free filings repository, structured
   financials for MG corporates will likely require manual sourcing
   (audit reports, banking partners) — out of scope for the free MVP.
