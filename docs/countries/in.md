# 🇮🇳 India — GLEIF + BSE

## Identifier

- Primary: `CIN` (Corporate Identity Number) — 21 alphanumeric chars.
  Structure: `[LU] + 5-digit industry + 2-char state + 4-digit year + 3-char classification + 6-digit reg number`.
  Example: `L17110MH1973PLC019786` = Reliance Industries Limited.
- Secondary: `GSTIN` (15 chars, state-prefixed) — mapped to `IdentifierType.VAT`.
- `PAN` (10 chars) is embedded inside CIN and not separately queryable for free.

## Python module note

The module folder is `packages/adapters/in_/` (trailing underscore) because
`in` is a Python reserved keyword. Import as:

```python
from packages.adapters.in_ import INAdapter
```

## Sources

- **GLEIF LEI records** (free, no key) — search + CIN lookup:
  https://api.gleif.org/api/v1/lei-records
  Indian entities carry their MCA CIN in `entity.registeredAs`, so the Global
  LEI index doubles as a free, key-less CIN lookup and name search. Filters
  used: `filter[entity.legalName]` + `filter[entity.legalAddress.country]=IN`
  for search, `filter[entity.registeredAs]={CIN}` for lookup.
- **BSE Annual Reports JSON** (free, no key) — financials:
  https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}
  Returns filed annual-report PDFs per BSE scrip code. Scrip code is resolved
  from the company's legal name via BSE PeerSmartSearch
  (`/BseIndiaAPI/api/PeerSmartSearch/w?Type=SS&text={name}`). Both api.bseindia.com
  routes require a browser User-Agent and a `bseindia.com` Referer header.
- **Auth**: None for any of the above.
- **Rate limit**: We self-throttle to 30 req/min.
- **robots.txt / ToS**: GLEIF data is CC0 open data. BSE JSON endpoints back
  the public bseindia.com site; used for non-commercial lookups with attribution.

### Why not MCA21

The MCA V3 migration retired the old `mcafoportal/viewCompanyMasterData.do`
master-data route — it now 302s to `errorpage.html` (verified 2026-07). The V3
master-data screen sits behind a login. GLEIF provides registry-grade identity
data (legal name, address, status, legal form, CIN, LEI) for free without a
session or CAPTCHA.

## Test companies

- Reliance Industries Limited — `L17110MH1973PLC019786`
- Tata Consultancy Services — `L22210MH1995PLC084781`
- Infosys Limited — `L85110KA1981PLC013115`
- HDFC Bank Limited — `L65920MH1994PLC080618`

## Status

🟢 **Working** — name search ✅; CIN lookup ✅; financials ✅ (listed companies).

### What works

- `search_by_name(name)` — GLEIF `filter[entity.legalName]` scoped to India.
  Returns `CompanyMatch` per entity with the MCA CIN (COMPANY_NUMBER) and LEI,
  legal name, registered address, and status. The exact/closest legal name
  ranks first.
- `lookup_by_identifier(COMPANY_NUMBER, CIN)` — GLEIF `filter[entity.registeredAs]`.
  Returns `CompanyDetails` (legal name, status, ELF legal-form code, registered
  address, industry SIC from CIN, CIN + LEI identifiers). Returns `None` for a
  CIN with no LEI record.
- `fetch_financials(CIN, years)` — for listed companies (CIN prefix `L`):
  resolves the BSE scrip code from the GLEIF legal name via BSE PeerSmartSearch,
  then lists filed annual reports (year + real per-company PDF `document_url`)
  from BSE `AnnualReport_New`. PDFs are the company's actual filed reports
  (verified `application/pdf`, multi-MB downloads). Returns `[]` for unlisted
  (`U…`) companies.

### Coverage limits

- **CIN lookup / search require an LEI.** Every listed company and the large
  body of firms that trade or borrow internationally hold LEIs and resolve
  cleanly. Purely domestic small private companies without an LEI return `None`
  / no match — an honest gap, not mock data.
- **`fetch_financials` covers listed (`L…`) companies only.** Unlisted company
  filings sit behind MCA21 paid per-document downloads (₹100/doc) — out of
  scope for the free MVP.
- **GSTIN (`VAT`) lookup** raises `AdapterNotImplementedError` — the gst.gov.in
  full lookup is OTP-gated.

## Recommended next steps

1. Parse the BSE annual-report PDFs (or the BSE XBRL financial-results endpoint
   per scrip code) into structured Ind-AS balance sheets feeding the risk engine.
2. Add a local CIN index from the monthly MCA Open Data CSV dumps to extend
   search/lookup to LEI-less domestic companies.
3. Fall back to NSE corporate-filings JSON for companies listed only on NSE.
