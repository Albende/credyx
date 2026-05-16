# 🇳🇿 New Zealand — NZBN Register (Companies Office / MBIE)

## Identifiers

- Type: `COMPANY_NUMBER` (primary)
  - **NZBN** — New Zealand Business Number, 13 digits (e.g. `9429036018110`).
  - **Companies Office Number** — 1-7 digit integer (e.g. Air NZ = `13468`).
- Type: `VAT`
  - **GST Number** — 9 digits. The NZBN API does **not** support GST lookup;
    callers must use `search_by_name` and then resolve to NZBN.

## Sources

- API portal: https://api.business.govt.nz/api-portal/
- NZBN API base: `https://api.business.govt.nz/services/v5/nzbn`
- **Auth**: Yes — `NZ_NZBN_API_KEY` (free, instant signup).
- **Header**: `Ocp-Apim-Subscription-Key: {key}`
- **Rate limit**: 100 req/min default; adapter throttles to 90.
- **robots.txt / ToS**: API usage governed by the api.business.govt.nz portal
  terms; no scraping required.

## Endpoints used

| Purpose | Method | Path |
|--------|--------|------|
| Search by name | GET | `/entities?search-term={text}&page-size={n}` |
| Lookup by NZBN | GET | `/entities/{nzbn}` |
| Lookup by Companies Office number | GET | `/entities?company-number={cn}&page-size=1` |
| Financial reports | GET | `/entities/{nzbn}/financial-reports` (falls back to `/entities/{nzbn}/documents`) |

## Test companies

| Name | NZBN | Companies Office # |
|------|------|--------------------|
| Fonterra Co-operative Group Limited | 9429036018110 | 1444589 |
| Air New Zealand Limited | 9429000003834 | 13468 |
| Spark New Zealand Limited | 9429036184563 | 110084 |
| Mainfreight Limited | 9429001129694 | 244611 |

## Status

- ✅ **Live** — registry search and lookup (NZBN or Companies Office number).
- 🟡 **Financials limited** — NZ Companies Office only requires filed
  financial statements from "large" companies, FMC reporters, and overseas
  companies registered in NZ. Most small NZ companies will return `[]` from
  `fetch_financials`. Listed entities (Fonterra, Air NZ, Spark, Mainfreight)
  generally do file. Statements are exposed by the NZBN API as PDF document
  URLs (XBRL not currently provided here — listed-company XBRL is at NZX,
  a separate source not wired in this MVP).

## Limitations

- GST lookup is not directly supported by the NZBN API; raises
  `InvalidIdentifierError` instructing the caller to use `search_by_name`.
- The `/financial-reports` endpoint shape is undocumented for some entity
  types; the adapter defensively parses multiple field names and falls back
  to `/documents`.
- Shareholder data is not exposed by the NZBN API.

**Recommended next step:** Wire `pypdf` extraction so the LLM can read
filed PDFs returned from `fetch_financials`. For NZX-listed companies,
add a parallel XBRL fetch from NZX disclosures.
