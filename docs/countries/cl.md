# 🇨🇱 Chile — SII (Servicio de Impuestos Internos) + CMF

## Identifier

- Type: `VAT` (primary, since the RUT doubles as the corporate tax ID)
  with `COMPANY_NUMBER` accepted as an alias.
- Format: **RUT** (Rol Único Tributario) — 7-9 digits plus a Mod-11
  check character, displayed `XX.XXX.XXX-X`. The check char is a
  decimal digit, or `K` when the remainder is 10.
- Validation: weighted sum with cycling factors 2..7 from the right,
  `mod 11`, then `11 − rem` mapped (11→"0", 10→"K", else digit). The
  adapter normalizes input — strips `CL` prefix, dots, dashes, spaces —
  and rejects bad check digits before any HTTP call.

## Sources

- **SII RUT verifier**: `https://zeus.sii.cl/cvc_cgi/stc/getstc`
  - Free public HTML form (`PRG=STC&OPC=NOR&RUT=<digits>&DV=<check>`).
  - Returns legal name, taxpayer status, and CIIU economic-activity
    codes — when the CAPTCHA gate lets the request through.
  - In practice the public endpoint almost always answers direct GETs
    with `alert('Por favor reingrese Captcha'); history.go(-1);` —
    the adapter detects that and raises `BlockedByRegistryError`.
- **CMF (Comisión para el Mercado Financiero)** entity portal:
  `https://www.cmfchile.cl/institucional/mercados/entidad.php?rut={digits}`
  - Free per-entity page for supervised (listed, banking, insurance)
    issuers; annual reports (memorias) are listed as downloadable PDFs.
  - The adapter surfaces this URL as `FinancialFiling.document_url` —
    structured line-item parsing is a Phase-2 add (multi-page filings
    index, no public API).
- **Open data**: `https://datos.gob.cl/` publishes a monthly SII
  tax-payer dump that includes company names; it is multi-GB and not
  suitable for live querying. Reserved for a future bulk ingest job.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🔴 Not implemented — SII has no free name API |
| Lookup by RUT | 🟡 Implemented; SII CAPTCHA blocks most requests in practice |
| Financials | 🟡 CMF discovery URL only (listed/regulated entities) |

`search_by_name` raises `AdapterNotImplementedError` per the
no-mock-data rule. `lookup_by_identifier` raises
`BlockedByRegistryError` when SII serves the CAPTCHA page, surfacing
the real state instead of fabricating a record.

## Why no paid sources

InfoBoletin, ChileAtiende premium, Equifax/Dicom and Sinacofi all have
paid APIs that bypass the CAPTCHA wall — out of scope for the MVP.
Phase 2 should evaluate a Playwright pool + 2Captcha integration
behind `packages/adapters/_base/browser.py`, or a paid Equifax CL feed.

## Rate limit

`rate_limit_per_minute = 30`. SII has no documented per-IP quota but
the CGI endpoint is single-threaded and slow; staying well under 1 RPS
avoids surprises.

## Test companies

- Empresas COPEC S.A. — `90.690.000-9`
- LATAM Airlines Group S.A. — `89.862.200-2`
- Banco de Chile — `97.004.000-5`
- Falabella S.A. — `90.749.000-9`

All four pass the Mod-11 checksum and exercise the SII / CMF paths.

## Status

🟡 **Partial-live**. RUT validation + normalization is fully working
and well-tested. SII lookup is wired but routinely blocked by CAPTCHA;
when it passes, the HTML scrape is defensive (best-effort label and
CIIU extraction). CMF financial filings expose a discovery URL only.

**Recommended next steps:**

1. Add a Playwright-based SII fetcher behind the browser pool so the
   CAPTCHA can be solved or session-cached. Keep the httpx fast-path
   for retries against cached pages.
2. Parse CMF "Información Financiera" pages per RUT to populate
   `FinancialFiling.structured_data` (balance sheet, income statement
   from the CL-IFRS XBRL filings the CMF publishes).
3. Build a one-shot importer for the monthly datos.gob.cl SII dump
   into Postgres so `search_by_name` can be served from a local
   mirror without scraping.
