# Ireland — CRO (Companies Registration Office)

## Identifier

- Primary: `COMPANY_NUMBER` — CRO Number, 1–7 digits (numeric).
  Normalize: strip whitespace and leading zeros.
- Secondary: `VAT` — Irish VAT in the form `IE` + 7 digits + 1–2 letters
  (e.g. `IE6388047V`). Accepted for validation only; the CRO API is **not
  indexed by VAT**, so `lookup_by_identifier(VAT, ...)` raises
  `InvalidIdentifierError`. Use the EU VIES adapter for VAT validation.

## Sources

- **Primary API**: CRO Web Services (CWS) — `https://services.cro.ie/cws/`
  - Auth: HTTP Basic. Credentials are free upon registration with the CRO
    but the live endpoints respond `401 Unauthorized` without them. Set
    env vars `IE_CRO_API_USERNAME` and `IE_CRO_API_PASSWORD`.
  - Rate limit: not documented publicly. Adapter caps at 60 req/min.
  - Response format: JSON (with `Accept: application/json` header and
    `htmlEnc=1` query param).
  - robots.txt / ToS: documented public service; respectful crawling
    permitted.

### Endpoints used

| Op | URL | Notes |
|----|-----|-------|
| Health | `GET /cws/status` | Unauthenticated. Returns `ServiceStatus` payload. |
| Search | `GET /cws/companies?company_name={name}&company_bus_ind=C&searchType=3&max={n}&htmlEnc=1` | `searchType=3` = "contains phrase". |
| Detail | `GET /cws/company/{cro_num}/C?htmlEnc=1` | `C` = companies (vs `B` business names). |
| Submissions | `GET /cws/company/{cro_num}/C/submissions?htmlEnc=1` | Lists filed documents. |
| Document | `GET /cws/submission/{submission_num}/{doc_num}` | **Paid** (€2.50 / doc). URL only — never fetched. |

## Financials

- Annual returns are filed yearly as B1 forms with abridged accounts.
- The adapter lists submissions and filters to entries whose type contains
  `B1`, `ANNUAL RETURN`, `ACCOUNTS`, or `FINANCIAL`.
- PDFs are paid through CRO; adapter returns metadata + the CRO direct
  download URL with `structured_data=None`. No PDF retrieval, no parsing,
  no mock numbers.

## Test companies

| Company | CRO | Notes |
|---------|-----|-------|
| Ryanair Holdings plc | 249885 | Used by tests. |
| Ryanair DAC | 104547 | Operating company. |
| Smurfit Kappa Group plc | 433527 | |
| CRH plc | 12965 | |
| Kerry Group plc | 31769 | |
| Bank of Ireland Group plc | 593672 | |

## Status

LIVE — when CRO API credentials are configured. Without credentials the
adapter reports `degraded` from `health_check()` and raises `AdapterError`
on calls (the API surface translates that to a non-`501` failure).

## Limitations

- Filing PDFs cost €2.50 each; only metadata + paid CRO URL are returned.
- VAT lookup is unsupported by CRO and rejected with
  `InvalidIdentifierError`. Use EU VIES for IE VAT validation.
- The CWS API was rate-limit-undocumented at integration time — keep the
  adapter cap conservative.
