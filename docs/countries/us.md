# 🇺🇸 United States — SEC EDGAR

## Identifier

- Type: `CIK`
- Format: 10-digit, zero-padded. Example: 0000320193 = Apple Inc.

## Sources

- https://www.sec.gov/cgi-bin/browse-edgar ; https://data.sec.gov
- **Auth**: No key — but the SEC requires a descriptive User-Agent with contact email (`SEC_EDGAR_USER_AGENT`).
- **Rate limit**: 10 req/sec (global SEC rule).
- **robots.txt / ToS**: Allowed under the SEC's documented UA rule.

## Test companies

- Apple Inc. (0000320193); Microsoft (0000789019); Tesla (0001318605); NVIDIA (0001045810).

## Structured XBRL financials

`fetch_financials()` calls
`GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` and
populates `FinancialFiling.structured_data` from the US-GAAP taxonomy.
404 responses (non-reporting filers) return an empty list. The per-CIK
JSON payload is cached in-process for the lifetime of the worker so
multiple year extractions hit SEC once.

### Schema (matches the ESEF parser)

```jsonc
{
  "currency": "USD",
  "period_end": "2023-12-31",
  "consolidated": true,
  "balance_sheet": {
    "total_assets": ..., "current_assets": ..., "noncurrent_assets": ...,
    "cash": ..., "inventory": ..., "receivables": ...,
    "total_liabilities": ..., "current_liabilities": ..., "noncurrent_liabilities": ...,
    "equity": ..., "retained_earnings": ...
  },
  "income_statement": {
    "revenue": ..., "cost_of_sales": ..., "gross_profit": ...,
    "operating_profit": ..., "net_income": ...,
    "depreciation_amortization": ..., "interest_expense": ...
  },
  "cash_flow": {
    "operating_cf": ..., "investing_cf": ..., "financing_cf": ...
  },
  "raw_concepts": { "Assets": ..., "Revenues": ..., "...": ... }
}
```

### US-GAAP concepts consumed

| Normalized field | US-GAAP concepts (first non-null wins) |
|------------------|----------------------------------------|
| `total_assets` | `Assets` |
| `current_assets` | `AssetsCurrent` |
| `noncurrent_assets` | `AssetsNoncurrent` |
| `cash` | `CashAndCashEquivalentsAtCarryingValue` |
| `inventory` | `InventoryNet` |
| `receivables` | `AccountsReceivableNetCurrent` |
| `total_liabilities` | `Liabilities` |
| `current_liabilities` | `LiabilitiesCurrent` |
| `noncurrent_liabilities` | `LiabilitiesNoncurrent` |
| `equity` | `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| `retained_earnings` | `RetainedEarningsAccumulatedDeficit` |
| `revenue` | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet` |
| `cost_of_sales` | `CostOfRevenue`, `CostOfGoodsAndServicesSold` |
| `gross_profit` | `GrossProfit` (or `revenue - cost_of_sales` if missing) |
| `operating_profit` | `OperatingIncomeLoss` |
| `net_income` | `NetIncomeLoss` |
| `depreciation_amortization` | `DepreciationAndAmortization`, `DepreciationDepletionAndAmortization` |
| `interest_expense` | `InterestExpense` |
| `operating_cf` | `NetCashProvidedByUsedInOperatingActivities` |
| `investing_cf` | `NetCashProvidedByUsedInInvestingActivities` |
| `financing_cf` | `NetCashProvidedByUsedInFinancingActivities` |

### Selection rules

- Only annual `10-K` facts with `fp == "FY"` are considered. Quarterly
  (`10-Q`, `fp == "Q*"`) data is ignored — restatement noise is too high.
- When multiple facts cover the same fiscal-year end, the latest `filed`
  date wins (latest restatement).
- Missing concepts stay null — never imputed.

## Status

✅ **Live** — search + lookup + structured XBRL financials (US-GAAP).

**Recommended next step:** Add state-level Secretary-of-State adapters (DE, CA, NY, TX, FL) — EDGAR only covers SEC-registered issuers.
