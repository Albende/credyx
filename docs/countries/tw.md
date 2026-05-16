# 🇹🇼 Taiwan — GCIS (Ministry of Economic Affairs)

## Identifier

- Type: `VAT` (UBN — 統一編號, Unified Business Number)
- Format: 8 digits, e.g. `22099131` = TSMC.
- Doubles as both tax ID and commercial-registry ID — there is no separate
  company number in Taiwan.
- Checksum: weights `(1,2,1,2,1,2,4,1)`. Sum each digit*weight reduced to its
  digit-sum; the total must be `≡ 0 (mod 10)`. If the 7th digit is `7`, both
  residues `0` and `9` are accepted.

## Sources

### Registry — GCIS open data
- Base: `https://data.gcis.nat.gov.tw/od/data/api/`
- Datasets used:
  - **Company Detail** — `5F64D864-61CB-4D0D-8AD9-492047CC1EA6` (full record, primary)
  - **Company Basic Info** — `6BBA2268-1367-4B42-9CCA-BC17499EBE8C` (fallback)
- OData query syntax — `$format=json`, `$filter=Business_Accounting_NO eq {ubn}`,
  `$top=N`. The endpoint **only filters on `Business_Accounting_NO`** —
  attempts to filter on `Company_Name`, `Responsible_Name`, or any other field
  return an empty body. The dedicated fuzzy name search at
  `findbiz.nat.gov.tw` blocks programmatic clients (403). Free-text name
  search therefore raises `AdapterNotImplementedError`; pass a UBN instead.
- **Auth**: none. Free.
- **Rate limit**: not strictly enforced; we throttle to 60/min.
- **robots.txt / ToS**: allowed (open-data portal).
- Public company page (for `source_url`):
  `https://findbiz.nat.gov.tw/fts/query/QueryBar/queryInit.do?keyword={ubn}`

### Financials — MOPS (best-effort)
- TWSE Public Information Observation:
  `https://mopsfin.twse.com.tw/server-java/t164sb01?step=1&CO_ID={ubn}&SYEAR={year}&SSEASON=4&REPORT_ID=C`
- Covers **listed companies only** (TSMC, Hon Hai, MediaTek, ASUS…).
- No clean JSON API — the endpoint returns HTML with embedded XBRL/PDF links.
  We probe per year and return the URL when the page contains a filing marker.
- Unlisted companies have **no free financial source** — `fetch_financials`
  returns `[]` for them.

## Test companies

- TSMC — Taiwan Semiconductor Manufacturing Co., Ltd. (`22099131`, Stock 2330)
- Hon Hai Precision Industry / Foxconn (`04541302`, Stock 2317)
- MediaTek Inc. (`23362910`, Stock 2454)
- ASUSTeK Computer Inc. (`23638777`)

## Status

✅ **Live** — registry lookup by UBN via GCIS (real data, real responses).
🟡 **Partial** — `search_by_name`: UBN lookup only (free-text name search
unavailable on free GCIS OData; raises `AdapterNotImplementedError`).
🟡 **Partial** — financials best-effort: MOPS HTML index URLs for listed
firms; unlisted firms return `[]`.

**Recommended next step:** plug a proper MOPS XBRL parser into
`packages/risk/xbrl_*` so listed-company filings become structured data instead
of raw URLs.
