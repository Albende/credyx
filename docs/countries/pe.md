# 🇵🇪 Peru — SUNAT (RUC verifier) + SMV (listed-company filings)

## Identifier

- Type: `VAT` (primary, since RUC doubles as the corporate tax ID), plus
  `COMPANY_NUMBER` as an alias.
- Format: **RUC** (Registro Único de Contribuyentes) — 11 digits.
  - First two digits encode contributor type: `20` = corporate (persona
    jurídica). Companies are the only contributors we care about for
    credit-risk analysis.
- Validation: the adapter normalizes input (strips `PE` prefix,
  whitespace, dashes, dots) and verifies length + digit-only format.
  - **We do not enforce the published Mod-11 checksum.** SUNAT's
    canonical weight sequence (`5,4,3,2,7,6,5,4,3,2`) does not match
    every live RUC — historical/transitional records exist that fail
    strict validation but are nonetheless valid in SUNAT's database
    (e.g. `20100068133` Credicorp Capital). Per the no-mock-data rule,
    SUNAT itself is the authority on existence.

## Sources

- **Primary — SUNAT public RUC verifier**:
  `https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/jcrS00Alias?accion=consPorRuc&nroRuc={RUC}`
  - Auth: none.
  - Method: HTTP GET, response is HTML. We strip tags and pull labelled
    fields: `Número de RUC`, `Tipo Contribuyente`, `Estado del
    Contribuyente`, `Condición del Contribuyente`, `Domicilio Fiscal`,
    `Actividad(es) Económica(s)`.
  - Rate limit: undocumented; we self-throttle to 30 req/min.
  - **Status:** intermittent CAPTCHA wall. SUNAT periodically fronts
    requests with `txtCodigo`-style CAPTCHA challenges. When that
    happens the adapter raises `BlockedByRegistryError` and the health
    check reports `blocked`. The block is real, not a bug — we don't
    fabricate parsed values to mask it.
- **Listed-company filings — SMV (Superintendencia del Mercado de
  Valores)**: `https://www.smv.gob.pe/Frm_InformacionFinanciera.aspx?data={RUC}`
  - Auth: none.
  - SMV only covers listed/regulated entities. The adapter probes the
    discovery page once per call and looks for SMV's filing labels
    ("Información Financiera Anual", "Memoria Anual", "Estados
    Financieros Auditados"). If absent — i.e. the RUC isn't supervised
    by SMV — `fetch_financials` returns `[]`. No fabrication.
  - Structured line-item extraction would require parsing the per-year
    XBRL/PDF reports linked from the SMV page; that is Phase-2 work
    once the PDF pipeline lands (see `CLAUDE.md` → Cross-cutting
    infrastructure).

### Considered and rejected

- `apis.net.pe` / `apiruc.com` community wrappers around SUNAT — both
  require either a free token (`apis.net.pe`) or impose tight free-tier
  rate limits. The direct SUNAT JSP is the canonical free source; we
  don't add a community-wrapper hop that can disappear without notice.
  If/when SUNAT's CAPTCHA wall hardens, revisit.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🔴 Not implemented — SUNAT name search requires CAPTCHA token |
| Lookup by RUC | 🟡 Live when SUNAT serves; raises `BlockedByRegistryError` when CAPTCHA wall is up |
| Financials | 🟡 Live for SMV-supervised entities (discovery URL only); `[]` otherwise |

## Adapter config

- `country_code = "PE"`, `country_name = "Peru"`
- `identifier_types = [VAT, COMPANY_NUMBER]`, primary = `VAT`
- `requires_api_key = False`
- `rate_limit_per_minute = 30`

## Test companies

- Credicorp Capital S.A. — RUC `20100068133`
- Compañía de Minas Buenaventura S.A.A. — RUC `20100079501`
- Cementos Pacasmayo S.A.A. — RUC `20419387658`
- Unión de Cervecerías Peruanas Backus y Johnston S.A.A. (Backus
  Holdings) — RUC `20100113610`

## Status

🟡 **Partially live.** Lookup by RUC works when SUNAT is serving;
blocked behind CAPTCHA otherwise. SMV financial-filing discovery URL
returned for SMV-supervised RUCs (i.e. listed companies). Name search
not implemented.

**Recommended next steps:**

1. Wire SUNAT through the planned browser pool (`packages/adapters/_base/browser.py`)
   once it lands, so the CAPTCHA challenge can be solved on demand and
   `lookup_by_identifier` becomes reliably live.
2. Parse the SMV per-company XBRL/PDF filings into
   `FinancialFiling.structured_data` (balance sheet + P&L line items)
   once the PDF/XBRL pipeline is built.
3. For closed-capital / non-supervised firms there is no free
   alternative for filed balance sheets in Peru — credit signals will
   need to come from SUNAT status fields (`HABIDO`/`NO HABIDO`,
   `ACTIVO`/`SUSPENSION TEMPORAL`/`BAJA`) plus OpenSanctions screening.
