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
- **Lookup** (dataset `5F64D864`) — `$format=json`,
  `$filter=Business_Accounting_NO eq '{ubn}'`, `$top=1`. This dataset filters
  **only on `Business_Accounting_NO`**.
- **Name search** (dataset `6BBA2268-1367-4B42-9CCA-BC17499EBE8C`, 公司登記關鍵字查詢)
  supports fuzzy matching: `$filter=Company_Name like {keyword} and
  Company_Status eq 01`. The `like` operator **requires** an accompanying
  `Company_Status` clause (a bare `Company_Name like` returns an empty body).
  `01` = 核准設立 (active). GCIS matches on the registered **Chinese** name only,
  so Latin-script queries won't hit registry records. Pass a UBN to route
  straight to a precise lookup instead.
- **Auth**: none. Free.
- **Rate limit**: not strictly enforced; we throttle to 60/min.
- **robots.txt / ToS**: allowed (open-data portal).
- Public company page (for `source_url`):
  `https://findbiz.nat.gov.tw/fts/query/QueryBar/queryInit.do?keyword={ubn}`

### Financials — TWSE OpenAPI (free, key-free, structured JSON)
- Base: `https://openapi.twse.com.tw/v1`
- Covers **TWSE-listed companies only** (TSMC, Hon Hai, MediaTek, ASUS…).
- Flow:
  1. Listed-company master `opendata/t187ap03_L` maps
     `營利事業統一編號` (UBN) → `公司代號` (stock code). Company not present ⇒ not
     TWSE-listed ⇒ `fetch_financials` returns `[]`.
  2. Income statement `opendata/t187ap06_L_{ci|basi|bd|fh|ins|mim}` and
     balance sheet `opendata/t187ap07_L_{…}` (one taxonomy per industry:
     `ci`=general, `basi`=banks, `bd`=securities, `fh`=financial holding,
     `ins`=insurers, `mim`=other financial). We probe until the stock code
     is found.
- The endpoints publish the **latest filed period** only (one filing).
  Amounts are in **thousands of TWD**; the ROC `年度` is converted to Gregorian
  (`+1911`) and `季別` (quarter) sets `period_end`. Real line items land in
  `structured_data.balance_sheet` / `.income_statement` plus a full
  `raw_concepts` dump — never synthesized.
- TPEx/OTC (`www.tpex.org.tw/openapi`) and 興櫃 companies are not yet wired;
  they return `[]` today.
- Unlisted companies have **no free structured financial source** — `[]`.

## Test companies

- TSMC — Taiwan Semiconductor Manufacturing Co., Ltd. (`22099131`, Stock 2330)
- Hon Hai Precision Industry / Foxconn (`04541302`, Stock 2317)
- MediaTek Inc. (`聯發科技股份有限公司`, Stock 2454) — registered UBN `84149961`
  (the `23362910` in earlier notes is not the exchange-registered UBN)

## Status

✅ **Live** — registry lookup by UBN via GCIS (real data, real responses).
✅ **Live** — `search_by_name`: real fuzzy Chinese-name search via GCIS
keyword dataset (active companies), UBN input routes to a precise lookup.
✅ **Live** — financials: structured balance sheet + income statement from
TWSE OpenAPI for listed firms; unlisted / OTC firms return `[]`.

**Recommended next step:** add TPEx OpenAPI (`www.tpex.org.tw/openapi`) for
OTC-listed companies, and pull multi-year history from MOPS XBRL into
`packages/risk/xbrl_*` (TWSE OpenAPI exposes only the latest period).
