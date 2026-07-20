# Malaysia — GLEIF registry lookup + Bursa Malaysia filings

## Identifier

- Type: `COMPANY_NUMBER`
- Formats accepted (all map to the same identifier type):
  - **New** — 12 digits, e.g. `196501000672` (mandatory since 2019).
  - **Old** — up to 7 digits + check letter, e.g. `6463-H`, `20076-K`,
    `901914-V`. Stripped to `DIGITS-LETTER`, uppercase.
- Normalisation: strip whitespace, uppercase, accept `MY` / `CR:` prefix
  and a bare hyphenless `20076K` form. Anything else raises
  `InvalidIdentifierError` — no check-letter is ever invented.

A caller may pre-resolve a Bursa-listed issuer with the packed form
`BURSA:<stockCode>` (e.g. `BURSA:1295`) to skip the registration-number →
stock-code resolution `fetch_financials` otherwise performs.

## Sources

### Registry search + lookup — GLEIF (free, no key)

- Base: `https://api.gleif.org/api/v1`
- The Global LEI index. Every Malaysian legal entity with an LEI carries
  its SSM registration number in `entity.registeredAs` (e.g.
  `196501000672 (6463-H)`), validated by the local LOU against SSM.
- `search_by_name` → `GET /lei-records?filter[entity.legalName]={name}`
  `&filter[entity.legalAddress.country]=MY`. Returns `CompanyMatch` with the
  SSM new + old numbers and the LEI.
- `lookup_by_identifier` → `GET /lei-records?filter[fulltext]={reg_no}`,
  then confirms the returned record's `registeredAs` actually contains the
  requested number before returning `CompanyDetails` (name, status,
  incorporation date, registered address, identifiers).
- **Coverage caveat**: only entities that hold an LEI are found (the large,
  listed, and internationally-trading universe). Companies with no LEI
  return no match — never a fabricated one. `search_by_name` also covers
  only LEI-holding entities; there is no free full SSM name index.
- **Auth**: none. **Rate limit**: adapter throttles to 30 req/min.

### Financials — Bursa Malaysia (free, listed issuers)

- Base: `https://www.bursamalaysia.com` (Cloudflare-challenged — all calls
  route through `fetch_with_bot_bypass` / FlareSolverr).
- Stock-code resolution: `GET /api/v1/announcements/search?ann_type=company`
  `&keyword={name}` returns announcement rows whose company link carries
  `stock_code=NNNN`; the adapter matches the GLEIF legal name to pick the
  code.
- Annual reports: `GET /api/v1/announcements/search?ann_type=company`
  `&company={stock_code}&keyword=annual%20report`. Each row yields the
  announcement id, title (with financial year) and announcement date.
- PDF + period-end enrichment: the disclosure page
  `https://disclosure.bursamalaysia.com/FileAccess/viewHtml?e={ann_id}`
  carries the "Financial Year Ended" date and the real PDF attachment URL
  (`/FileAccess/apbursaweb/download?id=…`). `document_url` is set only when
  that attachment link is present.
- **Coverage**: ~1,000 issuers (Main / ACE / LEAP markets). Annual reports
  are free PDFs. Unlisted companies (no stock code) return `[]`.

### Registry — SSM e-Info (excluded, paid)

- URL: https://www.ssm-einfo.my/
- Operator: Companies Commission of Malaysia (SSM). Every full-record
  extract is billed per document and gated by login + reCAPTCHA. There is
  no free public per-company financial extract, so the paid registry is
  excluded per the project's "no paid APIs" rule.

### data.gov.my (open data, partial)

- URL: https://data.gov.my/
- Some SSM bulk datasets are republished here but they are sparse and not a
  substitute for a live lookup. Left as a Phase-2 ingestion candidate.

## Test companies

| Company | Reg # (new) | Reg # (old) | Bursa code |
|---------|-------------|-------------|------------|
| Public Bank Berhad | `196501000672` | `6463-H` | `1295` |
| Malayan Banking Berhad (Maybank) | `196001000142` | `3813-K` | `1155` |
| IHH Healthcare Berhad | `200101025419` | `901914-V` | `5225` |
| Petronas Gas Berhad | `198301006841` | — | `6033` |
| Tenaga Nasional Berhad | `199001007331` | — | `5347` |
| Petroliam Nasional Berhad (PETRONAS, parent — unlisted) | `197401002911` | `20076-K` | — |

New-format numbers above are as recorded in GLEIF (`registeredAs`). Note the
old MVP doc listed `197001000465` / `196601000142` for PETRONAS / Public
Bank and mapped stock code `5347` to Petronas Gas — those were incorrect;
`5347` is Tenaga Nasional and Petronas Gas is `6033`.

## Status

- `search_by_name` → live via GLEIF (LEI-holding MY entities).
- `lookup_by_identifier` → live via GLEIF for syntactically valid IDs whose
  entity holds an LEI; `None` when no LEI record matches; `400
  invalid_identifier` for malformed input.
- `fetch_financials` →
  - Registration number of a listed issuer → resolves to the Bursa stock
    code and returns annual-report filings (year, period-end, MYR, PDF
    `document_url`, per-filing `source_url`).
  - `BURSA:<code>` packed id → same, skipping the resolution step.
  - Unlisted or non-LEI companies → `[]`.

## Recommended next steps

1. Cache the SSM-number → Bursa stock-code mapping in Postgres so repeat
   `fetch_financials` calls skip the FlareSolverr resolution round-trip.
2. Pipe Bursa annual-report PDFs through the PDF extraction worker so
   `structured_data` is populated alongside the document URL.
3. Phase-2: paid SSM e-Info integration behind a feature flag to cover
   unlisted companies and full director/shareholder records.
4. Ingest bulk data.gov.my SSM datasets nightly so `search_by_name` can
   also return non-LEI entities.
