# 🇮🇱 Israel — ICA / data.gov.il

## Identifier

- Primary: `COMPANY_NUMBER` — 9 digits. Example: 520013954 = Teva Pharmaceutical Industries Ltd.
- Alias: `VAT` — Israeli companies use the same 9-digit number for VAT (Osek Murshe / Osek Patur for sole-traders use a different scheme, not covered here).

## Sources

- **Registry**: Israel Corporations Authority (Rasham Ha-Hevarot), Ministry of Justice.
- **Open data**: https://data.gov.il/dataset/ica_companies
- **CKAN API**: `https://data.gov.il/api/3/action/datastore_search?resource_id={resource_id}&q={query}`
- **Default resource id**: `f004176c-b85f-4542-8901-7b3176f9a054` (override with env `IL_ICA_RESOURCE_ID` if the publisher rotates it).
- **Auth**: No — free public CKAN.
- **Rate limit**: Soft, throttled client-side to 60 req/min.
- **robots.txt / ToS**: Open data, attribution requested.

### Listed-company financials

- TASE (Tel Aviv Stock Exchange): https://www.tase.co.il/en/market_data/securities
- Maya disclosure portal: https://maya.tase.co.il/
- No stable open JSON keyed by company number; HTML/PDF only. Out of MVP scope.

## Test companies

| Company | Company Number |
|---|---|
| Teva Pharmaceutical Industries Ltd. | 520013954 |
| Bank Hapoalim B.M. | 520000118 |
| Check Point Software Technologies Ltd. | 520043595 |
| NICE Ltd. | 520044106 |

## Status

🟡 **Partial** — search + lookup ✅ via data.gov.il CKAN. Financials ❌ — TASE/Maya integration deferred (no free structured feed).

## Notes

- Hebrew text is returned as UTF-8 by CKAN; the adapter preserves the original Hebrew name and surfaces an English alias when present (`"<English> / <Hebrew>"`).
- The dataset publishes column names in mixed casing across snapshots (e.g. `Company_Number` vs `company_number`) — the adapter tolerates both.
- For sole proprietors / partnerships not in the corporate register, use the Tax Authority Osek lookup (not free as a structured API, out of scope).

**Recommended next step**: parse Maya disclosure HTML for the top ~600 TASE-listed Israeli companies to extract annual report PDF URLs and link them in `fetch_financials`.
