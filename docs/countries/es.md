# 🇪🇸 Spain — einforma + GLEIF + ESEF (filings.xbrl.org)

## Identifier

- Primary: `CIF` (Código de Identificación Fiscal). Format: leading letter
  (org class) + 7 digits + check char (digit OR letter, depending on the
  leading letter). The Spanish VAT number is `ES` + the CIF/NIF.
- Also accepts `NIF` (same shape for companies, used interchangeably) and
  `VAT` (with or without the `ES` prefix — the adapter normalizes both).

## Sources

- **einforma** (free per-CIF preview) —
  `https://www.einforma.com/servlet/app/portal/ENTP/prod/ETIQUETA_EMPRESA/nif/{CIF}`
  Sourced from BORME / the Registro Mercantil. Returns the registered name,
  legal form, registered address, and CNAE activity for any Spanish CIF.
  Used to resolve a CIF to its real registered company in
  `lookup_by_identifier` and as the CIF→name bridge in `fetch_financials`.
  ISO-8859-1, HTML entities. No auth, no key.
- **GLEIF** (Global LEI Foundation) —
  `https://api.gleif.org/api/v1/lei-records` Free structured JSON:API.
  Powers `search_by_name` (fuzzy legal-name search filtered to
  `entity.legalAddress.country=ES`) and maps a registered name to its LEI
  inside `fetch_financials`. GLEIF folds accents, so ASCII-folded names
  match. No auth, no key.
- **filings.xbrl.org** — `https://filings.xbrl.org/api/filings` Free mirror
  of every EU ESEF (iXBRL) annual report, keyed by LEI. Supplies the real,
  downloadable filed accounts (ESEF package `.zip`, iXBRL viewer) for
  Spanish listed issuers in `fetch_financials`. No auth, no key.
- **VIES** (EU VAT Information Exchange) —
  `https://ec.europa.eu/taxation_customs/vies/rest-api/ms/ES/vat/{CIF}`
  REST JSON, no auth. Confirms the CIF is a valid Spanish VAT registration
  (`isValid`). Note: Spain does **not** disclose name/address via VIES (both
  fields return `---`), so VIES is used only as a validity signal — the name
  and address come from einforma.
- **BORME** — `https://www.boe.es/diario_borme/` Daily PDF Bulletin of the
  Mercantile Registry. No structured API, no name index; not wired here.
- **CNMV** — the old `InformacionEntidad.aspx?nif=` endpoint now 301s to an
  error page and its listing pages require a WebForms postback, so CNMV is
  no longer used directly; ESEF filings via filings.xbrl.org replace it.
- **Auth**: none.
- **Rate limit**: adapter throttles to 30 req/min.
- **robots.txt / ToS**: free registry aggregator + open XBRL/LEI data, used
  with attribution.

## Test companies

- Telefónica S.A. — CIF `A28015865` (listed, ESEF filer)
- Banco Santander S.A. — CIF `A39000013` (listed, ESEF filer)
- Iberdrola S.A. — CIF `A48010615` (listed, ESEF filer)
- Industria de Diseño Textil (Inditex) S.A. — CIF `A15075062` (listed)
- Note: `A15022510` is **Zara España S.A.** (an Inditex subsidiary), not the
  listed Inditex parent — earlier docs mislabeled it.

## Status

| Capability | Status | Notes |
|------------|--------|-------|
| Lookup (CIF/NIF/VAT) | ✅ LIVE | einforma name + address + legal form + CNAE; VIES VAT-validity. |
| Financials | ✅ LIVE | Real ESEF (iXBRL) annual reports for listed issuers via filings.xbrl.org (CIF→name→LEI). Private non-ESEF filers correctly return an empty list (no free filed accounts). |
| Name search | ✅ LIVE | GLEIF fuzzy legal-name search, ES-filtered, returns LEI-identified matches. |

**Follow-ups:**

- Wire an ESEF XBRL parser (`packages/risk/xbrl_esef.py`) to extract
  structured figures from the downloaded ESEF packages into
  `FinancialFiling.structured_data`.
- For private companies' financial statements the only source is the
  Registro Mercantil per-document paid lookup — out of scope for the
  free-only MVP; einforma still yields the identity/address for them.
