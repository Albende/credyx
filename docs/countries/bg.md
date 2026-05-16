# 🇧🇬 Bulgaria — Trade Register (Търговски регистър)

## Identifiers

- **EIK / UIC** (Edinen Identifikatsionen Kod) — `COMPANY_NUMBER`, 9 digits
  for the parent legal entity, 13 digits for branches / sub-units.
- **VAT** — `BG` + 9-digit EIK. Same number, different prefix.

## Sources

- **Trade Register & Register of NPLE** — Registry Agency, Ministry of
  Justice. Public portal: <https://portal.registryagency.bg/>
- **Public JSON API** (used by this adapter):
  - `GET /CR/api/Deeds/{eik}` — full canonical extract for a company.
    Returns JSON including all "Announced Acts" (annual financial
    reports, audit reports, management reports) as embedded fields with
    `DocumentAccess/{token}` PDF links. **Free, no auth.**
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
| `search_by_name` | ❌ | Portal does not expose a JSON name-search endpoint — the SPA renders results server-side. Adapter raises `AdapterNotImplementedError`. Look up by EIK or VAT instead. |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | `/CR/api/Deeds/{eik}` JSON. |
| `lookup_by_identifier(VAT)` | ✅ | Strips `BG` prefix, looks up same Deeds endpoint, also calls VIES to confirm VAT validity. |
| `fetch_financials` | ✅ | Annual financial reports + management/audit reports extracted from `CR_GL_ANNOUNCED_ACTS_L` section. PDF document URLs returned (no structured XBRL — Bulgaria does not yet publish iXBRL for non-listed firms). |

## Test companies (REAL)

- **Sopharma AD** — EIK 831902088 (listed pharmaceutical)
- **M+S Hydraulic AD** — EIK 833067548
- **Trakia-Papir AD** — EIK 115008470
- **Industrial Holding Bulgaria AD** — EIK 121144539

## Status

✅ **LIVE — full registry + free annual financial reports.**

## Future work

- Add `search_by_name` once a stable JSON endpoint is identified (the
  current SPA mediates all queries through a server-side controller).
- Parse the PDF annual reports into structured `FinancialFiling.structured_data`
  via the planned `packages/risk/pdf` pipeline.
- Map the full `legalForm` nomenclature from
  `/CR/api/nomenclatures` instead of the local subset.
