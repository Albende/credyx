# 🇦🇷 Argentina — AFIP padron (+ CNV for listed)

## Identifier

- Type: `VAT` (primary) and `COMPANY_NUMBER` — both map to CUIT.
- Format: 11 digits, displayed as `XX-XXXXXXXX-X` (e.g. `30-54668997-9`).
- Mod-11 checksum on the leading 10 digits, weights `5,4,3,2,7,6,5,4,3,2`.
- Prefix encodes entity type: `30/33/34` = company, `20/23/24/27` = natural
  person (sole traders included in padron).

## Sources

- **AFIP sr-padron v2**: `https://soa.afip.gob.ar/sr-padron/v2/persona/{cuit}`
  - JSON, free, no auth, no key.
  - Returns: `razonSocial`, `estadoClave`, `tipoPersona`, `domicilio[]`,
    `actividad[]`, incorporation / cease dates.
  - **Rate limit**: undocumented; throttled to 60 req/min by the adapter.
  - **robots.txt / ToS**: public consulta endpoint; respectful crawler UA.
- **AFIP web "constancia de inscripción"**:
  `https://servicioscf.afip.gob.ar/publico/consultas/consultaConstanciaAccion.aspx?cuit={cuit}`
  — human-readable source URL surfaced on `CompanyDetails.source_url`.
- **CNV (Comisión Nacional de Valores)**: `https://www.cnv.gov.ar/`
  — annual reports free for ~100 listed issuers. Not yet wired (no free
  CUIT→CNV symbol map; would require a scrape on every call).
- **IGJ (per-province corporate registries)**: paid extracts only — out of
  scope for the free MVP.

## Test companies

- YPF S.A. — `30-54668997-9`
- Banco Macro S.A. — `30-50001008-4`
- Grupo Galicia (Banco Galicia) — `30-50000173-5`
- Mercado Libre S.R.L. — `30-70308853-4`

## Status

✅ **Live** — identifier lookup against AFIP padron.

- `search_by_name`: ❌ `AdapterNotImplementedError` (AFIP padron does not
  expose name search).
- `lookup_by_identifier` (`VAT` / `COMPANY_NUMBER`): ✅
- `fetch_financials`: ⚠️ returns `[]` — CNV listed-co filings not yet wired.

**Recommended next steps:**

1. Wire CNV "información financiera" listing → map CUIT to issuer symbol
   for the ~100 publicly-traded firms and return their annual reports
   (PDF + XBRL where available).
2. Add OpenCorporates AR (free tier) or BCRA "central de deudores" as a
   name-search fallback so `search_by_name` can be implemented.
3. Evaluate scraping `https://www.cuitonline.com` (ToS-grey) for name
   search if no free official source surfaces.
