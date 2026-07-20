# 🇬🇷 Greece — GEMI + VIES

## Identifiers

- **GEMI number** (`COMPANY_NUMBER`): General Commercial Registry,
  typically 9 digits (legacy records up to 12 digits accepted).
- **ΑΦΜ / VAT** (`VAT`): 9 digits. EU VAT prefix is `EL`, not `GR`.
  Validated with the standard checksum (weights 256/128/64/32/16/8/4/2
  over the first 8 digits, sum mod 11; mod 10 → 0).

## Sources

- **GEMI publicity portal** — https://publicity.businessportal.gr/
  (endpoints re-verified 2026-07-20; the old `GET /api/companies?searchTerm=`
  and `GET /api/companies/{gemi}/details` paths now 404)
  - Search: `POST /api/searchCompany` with body
    `{"dataToBeSent": {...full envelope, "inputField": "<query>", "radioValue": "all", "page": 1}, "token": null, "language": "en"}`.
    The backend returns **500** unless the full `dataToBeSent` envelope the
    Next.js UI sends is present. Response: `{"total": {...}, "hits": [{id,
    gemiNumber, afm, name, title[], addressCity, legalType, status,
    isSuspended}]}`.
  - Detail: `POST /api/company/details` with body
    `{"query": {"arGEMI": "<gemi>"}, "token": null, "language": "en"}`.
    Response: `{"companyInfo": {"payload": {"company": {...}, "capital":
    [...], "decisions": [...], ...}}}`; 404 for unknown GEMI. Dates are
    DD/MM/YYYY.
  - Free, no auth — the browser sends a reCAPTCHA token but `token: null`
    is accepted today; if that ever changes the adapter will start failing
    and the token flow needs wiring.
- **VIES** SOAP — https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  - `countryCode=EL`, returns name + address for valid ΑΦΜ.
- **ATHEX** (listed companies only) — https://www.athexgroup.gr/web/guest/companies-financial-data
  - Free PDF annual reports. Index discovery is brittle JSP — not wired.

## Test companies

| Name | GEMI | ΑΦΜ |
|---|---|---|
| Hellenic Telecommunications Organization (OTE) | 1037501000 | EL094019245 |
| Coca-Cola 3E Ελλάδος (Hellenic bottling ops) | 677301000 | EL094277965 |
| OPAP S.A. | 3823201000 | EL090027346 |
| National Bank of Greece | 6062511000 | EL094014201 |

OTE (`1037501000`, status Active) and Coca-Cola 3E (`677301000`, status
Active, capital EUR 173,788,380) were re-verified against the live
`searchCompany` / `company/details` endpoints on 2026-07-20.

## Capabilities

| Capability | Status | Notes |
|---|---|---|
| `search_by_name` | ✅ | GEMI publicity portal (best-effort) |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | GEMI detail endpoint |
| `lookup_by_identifier(VAT)` | ✅ | VIES (`EL` prefix) |
| `fetch_financials` | ⚠️ | Returns `[]`; ATHEX index not yet wired |

- `requires_api_key = False`
- `rate_limit_per_minute = 30`

## Status

🟢 **Wired (MVP)**: name search + identifier lookup via GEMI publicity
portal and VIES. Financials are an explicit gap.

**Recommended next steps:**
1. Wire ATHEX listed-company annual report PDFs into `fetch_financials`
   once the PDF extraction pipeline lands.
2. Re-validate GEMI portal endpoints during the next adapter sweep — the
   JSON paths are undocumented and may shift.
3. Consider OpenSanctions enrichment for Greek shipping holdings (high
   sanctions-evasion risk profile).
