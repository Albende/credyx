# Malaysia — Bursa Malaysia (listed) + SSM e-Info (paid, excluded)

## Identifier

- Type: `COMPANY_NUMBER`
- Formats accepted (both map to the same identifier type):
  - **New** — 12 digits, e.g. `197001000465` (mandatory since Jan 2019).
  - **Old** — up to 7 digits + check letter, e.g. `20076-K`, `6463-H`,
    `901914-V`. Stripped to `DIGITS-LETTER`, uppercase.
- Normalisation: strip whitespace, uppercase, accept `MY` country prefix
  and a bare hyphenless `20076K` form. Anything else raises
  `InvalidIdentifierError` — no check-letter is ever invented.

A caller may pre-resolve a Bursa-listed issuer with the packed form
`BURSA:<stockCode>` (e.g. `BURSA:5347`) to skip the SSM-side resolution
this adapter cannot perform.

## Sources

### Registry — SSM e-Info (excluded, paid)

- URL: https://www.ssm-einfo.my/
- Operator: Companies Commission of Malaysia (SSM / Suruhanjaya Syarikat
  Malaysia).
- Status: **Paid, login + reCAPTCHA gated.** Every extract (Company
  Information / Profile / Financial Statement) is billed per document
  (from RM10). There is **no free public name-search or per-company
  lookup endpoint** — even the public landing page only previews the
  company name once you already know the registration number, and the
  rest of the record sits behind the paywall.
- Consequence: `search_by_name` and `lookup_by_identifier` raise
  `AdapterNotImplementedError` per the project's non-negotiable
  "no mock data, no paid APIs" rules.

### Financials — Bursa Malaysia (free, listed issuers only)

- Base: `https://www.bursamalaysia.com`
- API root: `https://www.bursamalaysia.com/api/v1`
- Endpoint (best-effort): `GET /announcements?stock_code={code}&type=annual-report`
- **Auth**: none.
- **Rate limit**: not strictly documented; this adapter throttles to
  30 req/min.
- **Coverage**: ~970 issuers listed on Bursa Malaysia (Main Market,
  ACE Market, LEAP Market). Annual reports are free PDFs; quarterly
  reports are also free but not pulled by this adapter.
- The Bursa JSON endpoint contract is not officially documented for
  third-party use. The adapter parses defensively: missing fields are
  skipped, never invented. If the endpoint changes shape `fetch_financials`
  returns `[]` rather than guessing.

### data.gov.my (open data, partial)

- URL: https://data.gov.my/
- Some SSM bulk datasets are republished here but they are sparse,
  often anonymised, and not a substitute for a live registry lookup.
  Not currently wired in; left as a Phase-2 ingestion candidate
  (nightly bulk dump → Postgres, queried as a local index).

### What is explicitly excluded (and why)

- **SSM e-Info paid extracts** — violates the "no paid commercial APIs"
  rule in the MVP.
- **Third-party aggregators** (e.g. SearchMyCompany, ringgitplus
  scrapers) — re-publish SSM data without licence and break under any
  reasonable ToS reading.
- **MyEG / LHDN tax-ID lookups** — restricted to authenticated taxpayer
  flows, no public API.

## Test companies

| Company | Reg # (new) | Reg # (old) | Bursa code |
|---------|-------------|-------------|------------|
| Petroliam Nasional Berhad (PETRONAS, parent — unlisted) | `197001000465` | `20076-K` | — |
| Petronas Gas Berhad (Bursa-listed subsidiary) | — | — | `5347` |
| Public Bank Berhad | `196601000142` | `6463-H` | `1295` |
| Malayan Banking Berhad (Maybank) | `196001000142` | `3813-K` | `1155` |
| IHH Healthcare Berhad | `200101025419` | `901914-V` | `5225` |

PETRONAS itself is wholly owned by the Malaysian government and is
unlisted; tests use **Petronas Gas Berhad** as the listed-issuer probe.

## Status

- `search_by_name` → **501 not_implemented** (SSM e-Info paywall).
- `lookup_by_identifier` → **501 not_implemented** for syntactically
  valid IDs; `400 invalid_identifier` for malformed input.
- `fetch_financials` →
  - Bursa-listed packed id (`BURSA:<code>`) → list of annual-report
    filings (PDF URLs where surfaced).
  - Plain registration number → `[]` (no free unlisted-issuer source).

## Recommended next steps

1. Phase-2: paid integration with SSM e-Info (per-doc billing flow)
   gated by a feature flag — keeps the MVP rule intact.
2. Ingest the bulk data.gov.my SSM datasets nightly into Postgres so
   `search_by_name` returns at least the public attributes (UEN, name,
   status) without hitting the paid registry.
3. Maintain a registration-number → Bursa-stock-code lookup table so
   listed-issuer financials can be fetched from a plain registration
   number without the `BURSA:` prefix.
4. Pipe Bursa annual-report PDFs through the planned PDF extraction
   worker so `structured_data` is populated alongside the document URL.
