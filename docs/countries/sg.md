# Singapore — ACRA (data.gov.sg) + SGX

## Identifier

- Type: `COMPANY_NUMBER`
- Format: **UEN** (Unique Entity Number), 9 or 10 alphanumeric characters,
  uppercase. Common shapes:
  - `nnnnnnnnX` — pre-2009 businesses (9 chars)
  - `yyyynnnnnX` — local companies, year-prefixed (10 chars; e.g. DBS Group
    Holdings `199901152M`, Singtel `199201624D`)
  - `TyyPQnnnnX` — entities issued by other agencies; `T19LL1234A` for LLPs,
    `S12LL0001D` for societies, etc.
- Normalization: strip whitespace, uppercase. No public checksum — the
  registry itself is the source of truth.

## Sources

### Registry — data.gov.sg CKAN (ACRA open data)

- Base: `https://data.gov.sg/api/action`
- Endpoint: `GET /datastore_search?resource_id={uuid}&q={query}&limit=N`
- Dataset: ACRA "Information on Corporate Entities". The resource UUID is
  republished periodically; the adapter defaults to
  `eba1b8e0-ddbd-4e15-aedb-2c0a1c89c0a3` and accepts an override via
  `SG_ACRA_RESOURCE_ID`. If health-check returns "resource not found",
  re-fetch the current UUID from
  https://data.gov.sg/datasets?topics=economy and set the env var.
- **Auth**: none. Free, open data.
- **Rate limit**: not strictly enforced — we throttle to 60/min.
- **robots.txt / ToS**: open-data portal, programmatic use allowed.
- **Returns**: UEN, entity name, status, entity type, registration /
  incorporation date, primary SSIC code, registered address. **No
  financials.**

### Financials — SGX (Singapore Exchange) public API, best-effort

- Base: `https://api.sgx.com`
- Keyword resolution: `GET /securities/v1.1/securities?params=keyword={q}`
  to map UEN/name → SGX stock code (e.g. DBS = `D05`, Singtel = `Z74`).
- Annual data: `GET /securities/v1.1/issuers/{stockCode}/companyDataAnnual`
- **Auth**: none.
- **Rate limit**: undocumented; conservative 60/min.
- **Coverage**: SGX-listed issuers only. Unlisted Singapore companies
  have **no free financial source** — ACRA BizFile+ Business Profile
  downloads are paid (S$5.50/doc) and excluded from the MVP per the
  non-negotiable "no paid APIs" rule.
- The SGX endpoint contracts are not officially documented for third-party
  use. The adapter parses defensively: missing fields are skipped, never
  fabricated. If the endpoint changes shape, `fetch_financials` returns
  `[]` rather than guessing.

### What is explicitly excluded (and why)

- **BizFile+ Business Profile** (`bizfile.gov.sg`) — S$5.50 per download,
  paid. Skipped.
- **OpenBizFile name search** — the public BizFile+ name-search form is
  free but session-/CAPTCHA-protected and not a documented API; the open
  ACRA data on data.gov.sg already covers the same registry attributes.

## Test companies

- DBS Group Holdings Ltd — UEN `199901152M`, SGX stock `D05`
- Singapore Telecommunications Limited (Singtel) — UEN `199201624D`,
  SGX stock `Z74`
- Wilmar International Limited — UEN `199904785Z`, SGX stock `F34`
- CapitaLand Investment Limited — UEN `200308573K`, SGX stock `9CI`

## Status

Live — `search_by_name` and `lookup_by_identifier` hit the real ACRA
open-data feed via data.gov.sg CKAN (no auth, no mock).

Partial — `fetch_financials` is best-effort: returns SGX annual report
records for listed issuers; returns `[]` for unlisted entities (the
spec-compliant outcome — we do not invent data).

**Recommended next steps**:

1. Maintain a UEN → SGX stock code lookup table (nightly job) instead of
   probing the SGX search endpoint per request.
2. Pipe SGX annual report PDFs through the planned PDF extraction worker
   (`pypdf` is already in `requirements.txt`).
3. Add an XBRL parser path for SGXNet-filed iXBRL annual reports so
   `structured_data` is populated alongside the document URL.
