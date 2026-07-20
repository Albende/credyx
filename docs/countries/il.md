# 🇮🇱 Israel — ICA / data.gov.il

## Identifier

- Primary: `COMPANY_NUMBER` — 9 digits. Example: 520013954 = Teva Pharmaceutical Industries Ltd.
- Alias: `VAT` — Israeli companies use the same 9-digit number for VAT (Osek Murshe / Osek Patur for sole-traders use a different scheme, not covered here).

## Sources

- **Registry**: Israel Corporations Authority (Rasham Ha-Hevarot), Ministry of Justice.
- **Open data**: https://data.gov.il/dataset/ica_companies
- **CKAN API**: `https://data.gov.il/api/3/action/datastore_search?resource_id={resource_id}&q={query}`
- **Default resource id**: `f004176c-b85f-4542-8901-7b3176f9a054` (verified current 2026-07-20; override with env `IL_ICA_RESOURCE_ID` if the publisher rotates it — discover the current id via `/api/3/action/package_show?id=ica_companies`).
- **Auth**: No — free public CKAN.
- **Rate limit**: Soft, throttled client-side to 60 req/min.
- **robots.txt / ToS**: Open data, attribution requested.

### Listed-company financials (TASE / Maya)

`fetch_financials` is wired to the Tel Aviv Stock Exchange disclosure system
"Maya". Two undocumented JSON hosts are read **key-free**:

- **Entity list** (company short-name → Maya `companyId`):
  `https://api.tase.co.il/api/content/searchentities?lang={1=en,2=he}`.
  Behind an Imperva WAF that only answers a whitelisted legacy user-agent
  (`Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; FSL 7.0.6.01001)`).
- **Per-company** (host `https://mayaapi.tase.co.il/api`, requires header
  `X-Maya-With: allow`):
  - `/company/alldetails?companyId={id}&lang=1` — carries `CorporateNo` (the
    9-digit registrar number), used to **verify** a name match.
  - `/company/financereports?companyId={id}&lang=1` — reporting periods
    (`CurrentPeriod` / `PreviousYear`, with `CurrencyCode`) and `LastReports`
    (the latest filed reports: `RptCd`, `Title`, `PubDate`).

The registrar company number is not in the entity list, so the adapter matches
the registry name (Hebrew or English) against Maya's short names, then confirms
each candidate's `CorporateNo` via `alldetails` before trusting the `companyId`.
Filings link to `https://maya.tase.co.il/en/reports/{RptCd}` (a real per-report
page); no numbers are fabricated. Non-listed / foreign-listed companies have no
Maya presence and return an empty list.

## Test companies

| Company | Company Number | Maya companyId | TASE-listed |
|---|---|---|---|
| Teva Pharmaceutical Industries Ltd. | 520013954 | 629 | ✅ (dual, USD) |
| Bank Hapoalim B.M. | 520000118 | 662 | ✅ (ILS) |
| NICE Ltd. | 520036872 | 273 | ✅ (dual, USD) |

Notes on the register: Check Point Software Technologies (previously listed
here as `520043595`) is **not** a TASE-listed entity — it trades on NASDAQ — and
does not appear in the ICA CKAN dataset, so it has no registry lookup or Maya
financials. The prior doc value for NICE (`520044106`) was wrong; the correct
registrar number, confirmed via Maya `CorporateNo`, is `520036872`.

## Status

🟢 **Working** — search + lookup ✅ via data.gov.il CKAN; financials ✅ via
TASE/Maya for listed companies (key-free). Non-listed companies correctly
return no filings rather than mock data.

## Notes

- Hebrew text is returned as UTF-8 by CKAN; the adapter preserves the original Hebrew name and surfaces an English alias when present (`"<English> / <Hebrew>"`).
- **The datastore columns are Hebrew names with spaces** (as of 2026-07): `מספר חברה` (company number, numeric), `שם חברה`, `שם באנגלית`, `סוג תאגיד`, `סטטוס חברה`, `תאריך התאגדות` (DD/MM/YYYY), `שם עיר`, `שם רחוב`, `מספר בית`, `מיקוד`. The adapter filters on `מספר חברה` and keeps the legacy English/underscore names as read-side fallbacks.
- **409 Conflict semantics**: CKAN returns 409 for ValidationError — filtering on an unknown column (schema drift) or a stale resource id — and data.gov.il also uses it when rate-limiting. The adapter raises a clear `AdapterError` explaining both causes; a rejected filter column automatically falls back to full-text `q` search.
- For sole proprietors / partnerships not in the corporate register, use the Tax Authority Osek lookup (not free as a structured API, out of scope).

**Recommended next step**: the Maya `financereports` payload also carries
structured `Balance` / `ProfitReport` rows for many domestic filers — parse
those into `structured_data` so the risk engine can compute ratios directly
instead of only linking the report page.
