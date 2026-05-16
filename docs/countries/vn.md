# 🇻🇳 Vietnam — National Business Registration Portal (NBR) + HOSE/HNX

## Identifier

- Types: `COMPANY_NUMBER`, `VAT` — the same value (Mã số thuế / MST).
- Format: 10 digits issued by the General Department of Taxation. Branch
  units append a 3-digit suffix (e.g. `0300588569-001`), giving 13 digits
  total. The MST doubles as the business registration code.
- Examples: Vinamilk `0300588569`, Vingroup `0101245486`,
  Vietcombank `0100112437`, FPT `0101248141`.

## Sources

- https://thongtindoanhnghiep.co — community JSON wrapper around the NBR.
  - Endpoints: `/api/company/search?k={query}&l={limit}&p={page}` and
    `/api/company/{mst}`.
  - **Auth**: No.
  - **Rate limit**: Soft — adapter throttles to 30 req/min.
  - **robots.txt / ToS**: Public; respectful crawling allowed.
- https://dangkykinhdoanh.gov.vn — official NBR portal (HTML-only,
  not used directly; the wrapper above mirrors its data).
- https://www.gdt.gov.vn — General Department of Taxation VAT validator
  (HTML, not consumed yet).
- https://www.hsx.vn (HOSE) and https://www.hnx.vn (HNX) — stock
  exchanges for listed-company annual reports. Free, HTML landing pages
  per ticker symbol.

## Test companies

- Vinamilk — Vietnam Dairy Products JSC, MST `0300588569`, HOSE: `VNM`.
- Vingroup JSC, MST `0101245486`, HOSE: `VIC`.
- Vietcombank, MST `0100112437`, HOSE: `VCB`.
- FPT Corporation, MST `0101248141`, HOSE: `FPT`.

## Status

✅ **Live** — search + lookup via thongtindoanhnghiep.co; financials
best-effort: HOSE/HNX URLs are emitted only for listed issuers whose
ticker landing page actually returns 200. Unlisted firms return `[]`.

**Recommended next step:** Wire EDINET-style XBRL ingestion once an
official Vietnamese filings endpoint becomes available; the HOSE/HNX
report pages are currently HTML-only.
