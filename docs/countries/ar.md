# 🇦🇷 Argentina — CNV (Comisión Nacional de Valores) issuer registry

## Identifier

- Type: `VAT` (primary) and `COMPANY_NUMBER` — both map to CUIT.
- Format: 11 digits, displayed as `XX-XXXXXXXX-X` (e.g. `30-54668997-9`).
- Mod-11 checksum on the leading 10 digits, weights `5,4,3,2,7,6,5,4,3,2`.
- Prefix encodes entity type: `30/33/34` = company, `20/23/24/27` = natural
  person.

## Sources

- **CNV AutoComplete (name search)**:
  `https://www.cnv.gov.ar/SitioWeb/Empresas/AutoComplete?term={name}`
  - JSON, free, no auth, no key. Returns `[{id, cuit, descripcion}]` for every
    issuer in the public-offering regime (oferta pública).
- **CNV issuer page (lookup + financials)**:
  `https://www.cnv.gov.ar/SitioWeb/Empresas/Empresa/{cuit}?formType=INFOFI&fdesde=1/1/{yyyy}`
  - Server-rendered (ASP.NET). Header carries razón social + régimen; the
    "Estados Contables" accordion lists each filed financial statement with its
    balance close date, accounting norm (NIIF/NCP) and balance type
    (CONSOLIDADO/INDIVIDUAL).
  - **Encoding quirk**: served as ISO-8859-1 while the header claims UTF-8 — the
    adapter decodes `resp.content` as `latin-1`.
- **CNV AIF filing viewer**:
  `https://aif2.cnv.gov.ar/presentations/publicview/{guid}`
  - The per-filing document page surfaced on `FinancialFiling.document_url`
    (e.g. YPF FY2025 → presentation #3488213, "YPF S.A. | 30546689979 - Estados
    Contables - NIIF"). Company- and filing-specific, not a generic landing.
- **Rate limit**: undocumented; throttled to 60 req/min by the adapter.

**Coverage note**: CNV only covers companies in the public-offering regime
(issuers of listed equity or negotiable obligations). A CUIT outside that
regime (e.g. a NASDAQ-only name with no local listing) returns `None` from
`lookup_by_identifier` and `[]` from `fetch_financials`.

**Retired source**: AFIP's free `sr-padron` v1/v2 REST endpoints now 404. The
surviving `ws_sr_constancia_inscripcion` padron service is SOAP behind a digital
certificate — out of scope for the key-free MVP.

## Test companies

All are CNV issuers (oferta pública):

- YPF S.A. — `30-54668997-9`
- Banco Macro S.A. — `30-50001008-4`
- Banco de Galicia y Buenos Aires S.A. — `30-50000173-5`
- Grupo Financiero Galicia S.A. — `30-70496280-7`

Note: MercadoLibre S.R.L. (`30-70308853-4`) is **not** a CNV issuer (NASDAQ:
MELI, no local public offering) and does not resolve — do not use it as an AR
test company.

## Status

✅ **Live** — CNV issuer registry (name search, CUIT lookup, estados contables).

- `search_by_name`: ✅ CNV AutoComplete JSON.
- `lookup_by_identifier` (`VAT` / `COMPANY_NUMBER`): ✅ issuer page header.
- `fetch_financials`: ✅ estados-contables filings (year, type, period_end,
  currency ARS, `document_url` → AIF filing viewer, accounting norm + balance
  type in `structured_data`).

**Recommended next steps:**

1. Follow the AIF `publicview` page one level deeper to the attached PDF/XBRL
   and wire it into the PDF text-extraction pipeline for ratio pre-computation.
2. Distinguish consolidated vs individual as separate filings if the risk
   engine wants both (today one statement per year is kept, preferring
   CONSOLIDADO).
3. Add a non-issuer fallback (e.g. GLEIF AR / OpenCorporates free tier) so
   companies outside the oferta-pública regime still get basic identity.
