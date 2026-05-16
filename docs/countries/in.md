# 🇮🇳 India — MCA21 + BSE/NSE

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

- **MCA21 Company Master Data** (free, HTML scrape):
  https://www.mca.gov.in/mcafoportal/viewCompanyMasterData.do?companyID={CIN}
- **MCA Open Data dumps** (monthly CSV, all active CIN + basic info):
  https://www.mca.gov.in/content/mca/global/en/data-and-reports/datasets.html
- **BSE Annual Reports** (free, listed companies):
  https://www.bseindia.com/corporates/ann.html
- **NSE Annual Reports** (free, listed companies):
  https://www.nseindia.com/companies-listing/corporate-filings-annual-reports
- **Auth**: None for any of the above.
- **Rate limit**: We self-throttle to 30 req/min. MCA21 is brittle under
  load; respect 5xx with backoff.
- **robots.txt / ToS**: MCA datasets are explicitly open. BSE/NSE pages
  permit non-commercial scraping with attribution.

## Test companies

- Reliance Industries Limited — `L17110MH1973PLC019786`
- Tata Consultancy Services — `L22210MH1995PLC084781`
- Infosys Limited — `L85110KA1981PLC013115`
- HDFC Bank Limited — `L65920MH1994PLC080618`

## Status

🟡 **Partial** — CIN lookup ✅; name search ❌ (CAPTCHA); financials ❌ (BSE
scripcode index not available for free).

### What works

- `lookup_by_identifier(COMPANY_NUMBER, CIN)` — scrapes MCA21 master data
  (name, status, class, incorporation date, registered office address,
  paid-up capital, email, industry SIC). Returns `None` for unknown CINs.

### What does not work in MVP

- **`search_by_name`**: MCA21's name search is session-bound and gated
  by a CAPTCHA. Raises `AdapterNotImplementedError` (501) per the
  no-mock-data rule. The intended replacement is to ingest the monthly
  MCA Open Data CSV dumps into Postgres and serve search from that index.
- **`fetch_financials`**: BSE annual reports are keyed by scripcode, not
  CIN; the free CIN→scripcode mapping is not exposed. Listed-company
  filings would require ingesting BSE's `EQ_ISINCODE.csv` master file
  (free) to build a CIN→scripcode index. Unlisted (`U…`) company
  filings live behind MCA21 paid per-document downloads (₹100/doc) —
  out of scope for the free MVP.

## Recommended next steps

1. Nightly ingest of MCA Open Data CSV dumps → Postgres → wire
   `search_by_name` to the local index.
2. Ingest BSE `EQ_ISINCODE.csv` (scripcode ↔ ISIN ↔ company name)
   nightly, then fuzzy-join CIN by company name to enable
   `fetch_financials` for listed companies (CIN prefix `L`).
3. Add NSE corporate-filings JSON endpoint (`/api/corp-info`) with the
   browser-style `Cookie` and `Referer` headers it requires.
4. Phase-2: integrate the BSE XBRL annual report endpoint per scripcode
   so structured balance-sheet data feeds into
   `packages/risk/xbrl_esef.py` (or an India-specific Ind-AS parser).
