# 🇹🇭 Thailand — DBD DataWarehouse + SET

## Identifier

- Primary: `COMPANY_NUMBER` — 13-digit Juristic Person ID issued by the
  Department of Business Development (DBD), e.g. `0107544000108` = PTT
  Public Company Limited.
- Alias: `VAT` — Thailand's tax ID is **the same 13-digit number** as the
  registration number. Both identifier types resolve to the same record.

Normalization: strip whitespace and hyphens; accept an optional leading
`TH` prefix; require exactly 13 digits.

## Sources

### Registry — DBD DataWarehouse

- Base: `https://datawarehouse.dbd.go.th`
- Name / juristic-ID search: `GET /api/search?key={query}&page=1&pageSize={N}`
- Company detail: `GET /api/company/{juristicId}` (with `/api/search` as a
  fallback shard).
- **Auth**: none. Free. The DBD DataWarehouse is the Ministry of
  Commerce's public open-data front-end.
- **Headers**: the JSON endpoints reject requests without a browser-style
  `Accept`, matching `Referer`, and `Origin` — we send all three.
- **Rate limit**: not strictly documented; we throttle to 30 req/min to
  stay polite (`rate_limit_per_minute = 30`).
- **Encoding**: UTF-8 Thai text — both `JuristicNameTH` (e.g. "บริษัท ปตท.
  จำกัด (มหาชน)") and `JuristicNameEN` are returned. The adapter prefers
  EN for display but exposes both via `raw`.
- **Returns**: juristic ID, Thai + English company names, registered
  address, registration date (Buddhist-era *or* Gregorian — both parsed),
  capital amount, juristic status, TSIC business code.

### Financials — SET (Stock Exchange of Thailand)

- Base: `https://www.set.or.th`
- Per-symbol annual statement page:
  `https://www.set.or.th/en/market/product/stock/quote/{symbol}/financial-statement/company-highlights?period=annual&year={year}`
- **Auth**: none.
- **Coverage**: **listed companies only** (PTT, SCB, AIS, CPALL, …). For
  unlisted Thai companies there is no free official financial source —
  `fetch_financials` returns `[]` rather than invent data.
- We probe each year over the requested window and only emit a filing
  when the SET page returns 200 with a financial-statement marker. The
  page is a SPA so we cannot extract structured XBRL from the HTML — we
  return the canonical URL for downstream PDF/scrape processing.

### Buddhist-era dates

DBD timestamps appear in two formats:

- ISO `YYYY-MM-DD` (Gregorian) — parsed directly.
- `DD/MM/YYYY` where the year is **Buddhist Era** (e.g. `01/10/2544` =
  2001-10-01). The adapter converts B.E. → Gregorian when the year is
  `> 2400`. Any other shape returns `None` — we never guess.

## Test companies

- PTT Public Company Limited — `0107544000108` (SET: PTT)
- Siam Commercial Bank PCL — `0107536000358` (SET: SCB)
- Advanced Info Service PCL — `0107535000311` (SET: ADVANC)
- CP All PCL — `0107542000011` (SET: CPALL)

## Status

✅ **Live** — search + lookup via DBD DataWarehouse (real data, no auth).
🟡 **Partial** — financials best-effort: SET URLs for listed firms; unlisted
firms return `[]`. The SET symbol must be present on the DBD record for
financials to resolve.

**Recommended next steps:**

1. Cache a Juristic ID → SET symbol mapping nightly from the SET listed
   companies feed so financials work even when DBD omits the symbol.
2. Plug a SET XBRL/iXBRL parser into `packages/risk/xbrl_*` so listed
   filings become `structured_data` instead of opaque URLs.
3. Add a fallback to SEC Thailand (sec.or.th) for non-SET issuers.
