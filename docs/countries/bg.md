# 🇧🇬 Bulgaria — Trade Register (Търговски регистър)

## Identifiers

- **EIK / UIC** (Edinen Identifikatsionen Kod) — `COMPANY_NUMBER`, 9 digits
  for the parent legal entity, 13 digits for branches / sub-units.
- **VAT** — `BG` + 9-digit EIK. Same number, different prefix.

## Sources

- **Trade Register & Register of NPLE** — Registry Agency, Ministry of
  Justice. Public portal: <https://portal.registryagency.bg/>
- **Public JSON API** (used by this adapter):
  - `GET /CR/api/Deeds/Summary?name={name}&selectedSearchFilter=1&page=1&pageSize=25&includeHistory=true`
    — legal-entity name search. Returns
    `[{ident, name, companyFullName, isPhysical}]`. **Free, no auth.**
  - `GET /CR/api/Deeds/{eik}` — full canonical extract for a company.
    Returns JSON including all "Announced Acts" (annual financial
    reports, audit reports, management reports) as embedded fields with
    `DocumentAccess/{token}` links. **Free, no auth.**
  - `GET /CR/api/Documents/{token}` — streams the actual filed PDF
    (`application/pdf`, `Content-Disposition` filename) for a
    `DocumentAccess` token. This is the real download endpoint; the
    `/CR/DocumentAccess/{token}` route only serves the JS viewer shell.
    **Free, no auth.**
- **VIES SOAP** at
  `https://ec.europa.eu/taxation_customs/vies/services/checkVatService` —
  used to confirm VAT registration; returns Cyrillic name + address.
- **Auth**: none. Bulk download / sworn registry copies are paid; the
  per-company JSON endpoint is free.
- **Rate limit**: undocumented; we throttle to 30/min.
- **robots.txt / ToS**: respected; we use a polite User-Agent and back
  off on 429 via `get_with_retry`.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | ✅ | `/CR/api/Deeds/Summary?name=…&selectedSearchFilter=1` JSON. Query in Cyrillic; physical persons are filtered out. Returns EIK + full company name. |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | `/CR/api/Deeds/{eik}` JSON. Name, status, legal form, registered address (`CR_F_5_L`), capital (`CR_F_31_L`). |
| `lookup_by_identifier(VAT)` | ✅ | Strips `BG` prefix, looks up same Deeds endpoint, also calls VIES to confirm VAT validity. |
| `fetch_financials` | ✅ | Annual financial reports + audit + management reports extracted from `CR_GL_ANNOUNCED_ACTS_L`. Each filing carries a **directly downloadable** `/CR/api/Documents/{token}` PDF URL. Reporting year is read from the filing text (`за YYYY г.` / `Година: YYYYг.`) — never inferred, deduped per `(year, type)`. No structured XBRL — Bulgaria does not publish iXBRL for non-listed firms. Note: many non-listed firms file their GFO with the NSI, not the register, so their register `fetch_financials` may be empty; listed companies (e.g. Sopharma) file in the register. |

## Test companies (REAL)

- **Sopharma AD** — EIK 831902088 (listed pharmaceutical). Verified for
  all three methods: name search, lookup, and `fetch_financials` returning
  downloadable 2023/2024 annual + audit report PDFs.
- **M + S Hydraulic AD** — EIK 123028180 (Kazanlak; lookup verified).
  Note: the previously listed 833067548 is a different entity
  ("Завод за каучукови уплътнители" AD) and was corrected.

## Status

✅ **LIVE — name search + full registry + directly downloadable annual
financial report PDFs.**

## Future work

- Parse the PDF annual reports into structured `FinancialFiling.structured_data`
  via the planned `packages/risk/pdf` pipeline.
- Map the full `legalForm` nomenclature from
  `/CR/api/nomenclatures` instead of the local subset.
