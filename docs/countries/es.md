# 🇪🇸 Spain — VIES + CNMV

## Identifier

- Primary: `CIF` (Código de Identificación Fiscal). Format: leading letter
  (org class) + 7 digits + check char (digit OR letter, depending on the
  leading letter). The Spanish VAT number is `ES` + the CIF/NIF.
- Also accepts `NIF` (same shape for companies, used interchangeably) and
  `VAT` (with or without the `ES` prefix — the adapter normalizes both).

## Sources

- **VIES** (EU VAT Information Exchange) —
  https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  SOAP endpoint, no auth. Confirms VAT validity and returns the registered
  name + address. Used for `lookup_by_identifier`.
- **CNMV** (Comisión Nacional del Mercado de Valores) —
  https://www.cnmv.es/Portal/Consultas/EE/InformacionEntidad.aspx?nif={cif}
  Free per-CIF lookup of listed-company filings (annual reports, XBRL).
  Used for `fetch_financials` when the CIF is CNMV-registered.
- **BORME** — https://www.boe.es/diario_borme/ Daily PDF Bulletin of the
  Mercantile Registry. No structured API, no name index; ingestion would
  require a PDF parsing pipeline (Phase 2 work, not wired here).
- **Auth**: none.
- **Rate limit**: VIES is unpublished but tolerant; adapter throttles to
  30 req/min.
- **robots.txt / ToS**: OK with attribution.

## Test companies

- Inditex S.A. — CIF `A15022510`
- Telefónica S.A. — CIF `A28015865`
- Banco Santander S.A. — CIF `A39000013`
- Iberdrola S.A. — CIF `A48010615`

## Status

| Capability | Status | Notes |
|------------|--------|-------|
| Lookup (CIF/NIF/VAT) | ✅ LIVE | VIES SOAP, name+address. |
| Financials | 🟡 PARTIAL | CNMV listed companies only; private firms’ accounts are paid Registro Mercantil. |
| Name search | 🔴 NOT AVAILABLE | No free authoritative source. Adapter raises `AdapterNotImplementedError`. |

**Phase 2 follow-ups:**

- Wire the CNMV entity page HTML parser to surface per-document XBRL/PDF
  URLs instead of pointing at the listing page.
- BORME daily PDF ingestion (Celery + pypdf) for private-company change
  events (incorporations, capital changes, director appointments).
- For private companies' financial statements, the only public source is
  the Registro Mercantil per-document paid lookup — out of scope for the
  free-only MVP.
