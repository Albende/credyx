# South Africa — GLEIF (CIPC-sourced) + SEC EDGAR

## Identifier

- Primary type: `COMPANY_NUMBER`
- Format: `YYYY/NNNNNN/NN` (year of incorporation / sequence / entity-type
  suffix, e.g. `/06` = (Pty)/Ltd, `/07` = public company, `/08` = NPC).
  CIPC stores the sequence **without** forced zero-padding, so the adapter
  preserves the digits given (e.g. Sasol `1979/003231/06`, Naspers
  `1925/001431/06`). Lookup transparently retries 6- and 7-digit sequence
  variants against GLEIF.
- Secondary type: `VAT` — 10 digits, must start with `4` (SARS rule).
  Lookup-by-VAT is not implemented (SARS has no free validation API).

## Sources

### GLEIF — free, key-free (search + lookup)

- URL: `https://api.gleif.org/api/v1/lei-records`
- Auth: none.
- Every South African entity with an LEI carries its CIPC registration
  number in `entity.registeredAs` (registration authority = CIPC), plus
  legal name, legal form, status, and registered address. GLEIF is an
  approved free aggregator under the project rules.
- Search: `filter[entity.legalName]=<name>` scoped by
  `filter[entity.legalAddress.country]=ZA` (partial/prefix match, precise).
- Lookup: `filter[entity.registeredAs]=<CIPC number>` scoped to ZA.

### CIPC BizPortal / eServices (gated — skipped)

- `https://eservices.cipc.co.za/` sells extracts behind an authenticated
  account; `https://www.bizportal.gov.za/bizprofile.aspx` now **redirects
  to `/login.aspx`** (POPIA, since 2024). Neither is scrapeable key-free,
  so both are out of scope per the no-paid-API / key-free rule.

### SEC EDGAR — free, key-free (financials, US-dual-listed issuers)

- `https://www.sec.gov/cgi-bin/browse-edgar` (name → CIK) +
  `https://data.sec.gov/submissions/CIK{10}.json`.
- The largest South African issuers that are **dual-listed in the US**
  file their audited annual report with the SEC as **Form 20-F**, served
  free and per-company from EDGAR. The adapter resolves the entity to its
  EDGAR CIK by name, confirms it is a South African filer (EDGAR country
  code `T3`) with a matching name, and returns the real filed 20-F
  documents (verified downloadable). Covers Sasol, Gold Fields, AngloGold
  Ashanti, Sibanye-Stillwater, Harmony, DRDGold, etc.
- SEC requires a descriptive User-Agent with contact — the adapter reads
  `SEC_EDGAR_USER_AGENT` (shared with the US adapter; has a working
  default). No key required.

### JSE / CIPC filed accounts (paid or gated — skipped)

- JSE market-data / SENS feeds are FTP/paid; the free SENS archive and
  client portal are login-gated. CIPC annual financial statements are paid
  eServices documents. Purely JSE-only issuers therefore have no free
  programmatic financial-statement surface, and `fetch_financials` returns
  `[]` for them rather than fabricate.

### SARS (tax authority)

- VAT validation requires an authenticated eFiling account; not publicly
  queryable. Skipped.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | OK | GLEIF legal-name search scoped to ZA. |
| `lookup_by_identifier` (COMPANY_NUMBER) | OK | GLEIF `registeredAs` lookup. |
| `lookup_by_identifier` (VAT) | NOT_IMPLEMENTED | SARS has no free API. |
| `fetch_financials` | OK (US-dual-listed) | SEC EDGAR 20-F; `[]` for JSE-only issuers. |

## Test companies

- Sasol Limited — `1979/003231/06` (JSE: SOL, NYSE: SSL) — **financials
  work**: SEC 20-F for FY2025/2024/2023.
- Naspers Limited — `1925/001431/06` (JSE: NPN) — search + lookup work;
  financials `[]` (its only 20-Fs predate the 3-year window / ADR delisted).
- Standard Bank Group Limited — `1969/017128/06` (JSE: SBK)
- MTN Group Limited — `1994/009584/06` (JSE: MTN)

Other South African issuers whose SEC 20-F is retrievable: Gold Fields
`1968/004880/06`, AngloGold Ashanti, Sibanye-Stillwater, Harmony Gold,
DRDGold.

## Status

OK — search + CIPC-number lookup via GLEIF (key-free); annual-report
financials via SEC EDGAR 20-F for US-dual-listed issuers (key-free,
verified downloadable). JSE-only issuers' filings remain behind paid CIPC
eServices.
