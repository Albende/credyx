# 🇵🇪 Peru — BVL / SMV listed-company data (dataondemand API)

## Identifier

- Type: `COMPANY_NUMBER` (primary) — the BVL **companyCode** (short numeric
  BVL issuer code, e.g. `61200`), plus `OTHER` as an alias carrier for the
  SMV **rpjCode** ("Registro Público del Mercado de Valores" code, e.g.
  `B20003`) and the exchange **ticker/nemónico** (e.g. `BVN`, `BUENAVC1`).
- The Peruvian tax id (**RUC**, 11 digits) is *not* carried by this source
  and is **not** an accepted identifier here — see "SUNAT" below for why.
- Resolution rules:
  - A digit-only value is treated as a BVL companyCode and looked up
    directly via `GET /v1/issuers/{companyCode}`.
  - A non-numeric value is treated as an rpjCode or ticker and resolved by
    scanning the full issuer list.
  - Start from a name via `search_by_name` when you don't have a code.

## Sources

- **Primary — BVL "data on demand" API** (`https://dataondemand.bvl.com.pe`),
  the public backend of the Bolsa de Valores de Lima, fed by the SMV
  (securities regulator). Auth: **none, no key**. JSON.
  - `GET /v1/issuers` — every listed/registered issuer: name, sector,
    address, website, founding date, tickers/ISINs (`listValue`), and the
    list of filed annual documents (`listMemoryEEFF`: Memoria Anual,
    Estados Financieros, gobierno corporativo, etc.).
  - `GET /v1/issuers/{companyCode}` — a single issuer record.
  - `GET /v1/financial-statements/{rpjCode}` — the issuer's audited
    financial ratios per year (Liquidez, Rotación de Activos, Solvencia,
    Deuda/Patrimonio, Rentabilidad de Patrimonio %, Valor en libros %).
  - Self-throttled to 30 req/min. Coverage is listed/registered issuers
    (~340 companies), not the whole SUNAT universe.

- **SUNAT RUC verifier — NOT USED (blocked).**
  `https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/jcrS00Alias` now
  fronts every RUC lookup with an **invisible reCAPTCHA v3** challenge
  (`site_key_sunat`, action `consultaRUC01`) and resets raw non-browser
  connections at the TLS layer. It cannot be read key-free / without
  solving a paid captcha, so per the no-mock-data rule we do not scrape it.

### Considered and rejected

- Community RUC wrappers — `apis.net.pe`, `api.decolecta.com`,
  `apiperu.dev`, `dniruc.apisperu.com`, `api.migo.pe` — **all now
  token-gated** (401/422 without a registered key). A user-registered key
  does not count as key-free, so none is wired in.
- SMV website (`www.smv.gob.pe`) — the old `Frm_InformacionFinanciera.aspx`
  endpoints 301-redirect to `gob.pe/smv` and no longer serve data; the same
  filings are exposed through the BVL dataondemand API used here.
- BVL EEFF document PDFs (`/eeff/{rpjCode}/…/*.PDF` paths in
  `listMemoryEEFF`) — the download host serves the SPA shell for these
  paths, so a working `document_url` could not be confirmed. We therefore
  surface the Memoria Anual reference inside `structured_data` but leave
  `document_url = None` rather than pass off a non-downloading URL.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🟢 Live — filters the BVL issuer list (accent-insensitive) |
| Lookup by identifier | 🟢 Live — BVL companyCode, or SMV rpjCode / ticker alias |
| Financials | 🟢 Live — per-year audited financial ratios as `structured_data` (PEN) |

## Adapter config

- `country_code = "PE"`, `country_name = "Peru"`
- `identifier_types = [COMPANY_NUMBER, OTHER]`, primary = `COMPANY_NUMBER`
- `requires_api_key = False`
- `rate_limit_per_minute = 30`

## Test companies

| Company | BVL companyCode | SMV rpjCode | Ticker |
|---------|-----------------|-------------|--------|
| Compañía de Minas Buenaventura S.A.A. | `61200` | `B20003` | `BVN` |
| Cementos Pacasmayo S.A.A. | `23950` | `CD0005` | `CPAC` |
| Unión de Cervecerías Peruanas Backus y Johnston S.A.A. | `21802` | `B30021` | `BACKUSI1` |
| Credicorp Ltd. | `73250` | `B60051` | `BAP` |

## Status

🟢 **Live.** Search, lookup, and financials all return real data key-free
from the BVL/SMV dataondemand API. Coverage is limited to listed /
registered issuers (the entities with public filed financials); there is
no free, key-less, captcha-free source for the general Peruvian company
universe (SUNAT RUC lookup is reCAPTCHA-v3 walled).

**Recommended next steps:**

1. Resolve a working BVL/SMV document host so `listMemoryEEFF` Memoria
   Anual / Estados Financieros PDFs can be attached as downloadable
   `document_url`s and parsed into line-item `structured_data` once the
   PDF pipeline lands.
2. If RUC-keyed lookup becomes a requirement, wire SUNAT through the
   planned browser pool + a reCAPTCHA-solving step (paid), or ingest the
   SUNAT "Padrón RUC" bulk open-data dump for offline RUC→name resolution.
3. Screen issuers against OpenSanctions before the LLM runs.
