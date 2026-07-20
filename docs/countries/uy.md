# 🇺🇾 Uruguay — RUPE (open-data registry) + BVM (issuer filings)

## Identifier

- Type: `VAT` (primary), `COMPANY_NUMBER` (alias).
- Format: **RUT** (Registro Único Tributario) — 12 digits, no separators
  in the canonical form. Common decorations (dots, dashes, the `UY`
  country prefix) are accepted and stripped by `_normalize_rut`.

## Sources

- **RUPE — Registro Único de Proveedores del Estado** (open data)
  - Portal: `https://catalogodatos.gub.uy` (CKAN).
  - Live query API (no key): `GET /api/3/action/datastore_search`
    - `?resource_id={latest}&q={name}` → name search.
    - `?resource_id={latest}&filters={"identificacion_prov":"{RUT}"}` → RUT lookup.
  - The adapter resolves the newest active monthly resource dynamically via
    `/api/3/action/package_search?q=registro-unico-de-proveedores-del-estado-rupe`
    (a new dataset is published each year, ~110k entities).
  - Fields: `identificacion_prov` (RUT), `denominacion_social_prov` (name),
    `domicilio_fiscal`, `localidad_prov`, `departamento_prov`, `estado_prov`
    (ACTIVO/…).
  - **Auth**: None. **Rate limit**: undocumented; adapter throttles to 30/min.
  - **Coverage note**: RUPE indexes entities registered to trade with the
    State (companies and individuals). Most private companies and many
    public ones appear; some pure state enterprises (e.g. ANCAP, UTE, ANTEL,
    BROU) are *not* listed as providers, so `lookup_by_identifier` returns
    `None` for those RUTs. The former DGI `JSConsRUTRest` JSON endpoint was
    retired and the DGI RUT web service now requires an X.509 client
    certificate, so RUPE is the free key-free registry.
- **BVM — Bolsa de Valores de Montevideo**
  - Issuer directories: `/operadores/emisores-de-acciones` and
    `/operadores/emisores-de-obligaciones-negociables` (map issuer name → id).
  - Per-issuer documents: `/operadores/documentos/{id}` — audited
    *Estados Contables*, *Memoria Anual*, etc., as directly-downloadable
    PDFs under `/repo/arch/{hash}.pdf`.
  - `fetch_financials` resolves the RUT → legal name via RUPE, matches it
    against the BVM issuer directory, and returns that issuer's filed
    financial-statement PDFs with real `document_url`s. Returns `[]` for
    companies that are not BVM-registered issuers.

## Test companies

- **PAMER S.A. — RUT `210000530018`** ✅ *(primary — passes all three)*.
  In RUPE (search + lookup) and a BVM issuer filing quarterly/annual
  *Estados Contables* (financials with downloadable PDFs).
- SAN ROQUE SOCIEDAD ANONIMA — RUT `210354300016` (in RUPE; BVM issuer id 79,
  historical filings).
- Broad name search examples: `PAMER`, `CONSTRUCCIONES`, `SAN ROQUE`.
- State enterprises ANCAP / UTE / ANTEL / BROU are **not** in RUPE (not
  registered as State providers); their RUT lookups return `None`.

## Capabilities

| Capability     | Status | Notes |
|----------------|--------|-------|
| Search by name | ✅ | RUPE `datastore_search` (`q=`); live, no key. |
| Lookup by RUT  | ✅ | RUPE `datastore_search` (`filters=`); `None` if not a registered provider. |
| Financials     | ✅ | BVM filed *Estados Contables* PDFs for BVM-registered issuers; `[]` otherwise. |

## Status

✅ **Live** — RUPE open-data registry for search + RUT lookup; BVM filed
financial-statement PDFs for listed issuers.

**Recommended next step:** Wire the BVM `document_url` PDFs into the
PDF text-extraction pipeline so the LLM can read the filed *Estados
Contables* text, and add a secondary registry source (e.g. AIN / DGI
certificate-gated service) to cover state enterprises absent from RUPE.
