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

### Registry — data.gov.sg datastore (ACRA open data)

- Base: `https://data.gov.sg/api/action`
- Endpoint: `GET /datastore_search?resource_id={id}&q=...&filters=...&limit=N`
  (the classic CKAN datastore endpoint still serves the current `d_…`
  dataset IDs; the legacy `eba1b8e0-…` UUID and the `/securities/v1.1/…`
  SGX endpoints from the first cut are both **dead** as of 2026).
- Dataset: ACRA "Information on Corporate Entities" (collection 2). Published
  as a **combined** roll-up plus **27 per-first-letter slices**:
  - Combined "Entities Registered with ACRA" —
    `d_3f960c10fed6145404ca7b821f263b87` (~2.1M rows; slim fields: UEN, name,
    status, entity type, `uen_issue_date`, street, postal). Used for
    name search and UEN lookup.
  - Per-letter slices A–Z + "Others" (richer: incorporation date, primary
    SSIC code, company type, full registered address, former names, audit
    firms). A UEN lookup routes to the matching slice by the entity name's
    first letter to enrich the record. The 27 dataset IDs are hard-coded in
    `SGAdapter.LETTER_RESOURCES` (stable; refetch from
    `https://api-production.data.gov.sg/v2/public/api/collections/2/metadata`
    if a slice starts 404-ing).
- **Search relevance**: field-scoped full-text query
  `q={"entity_name":"<name>"}` on the combined resource returns tightly
  ranked matches (plain `q=` fuzzes across all columns and ranks poorly).
- **Auth**: none. Free, open data.
- **Rate limit**: not strictly enforced — we throttle to 60/min.
- **robots.txt / ToS**: open-data portal, programmatic use allowed.
- **Returns**: UEN, entity name, status, legal form, incorporation date,
  primary SSIC code, registered address. **No financials.**

### Financials — SGX (Singapore Exchange) financial-reports feed

- Base: `https://api.sgx.com`
- Endpoint: `GET /financialreports/v1.0?pagestart={n}&pagesize=2000&params=id,companyName,documentDate,securityName,title,url`
  — the feed backing the public "Annual Reports & Related Documents" page.
  Returns every financial report filed by SGX-listed issuers, newest-first,
  each with an announcement `url` on `links.sgx.com`. There is **no**
  server-side company filter, so the adapter pages the feed (2000/page,
  capped at 8 pages) and matches issuers by normalized name, stopping once
  the page's oldest `documentDate` predates the requested window.
- **Document resolution**: each announcement `url` is an HTML detail page;
  the adapter fetches it and extracts the real filed PDF href
  (`…/{id}/{file}.pdf`, verified `application/pdf`) as `document_url`. The
  announcement page itself is the `source_url`.
- **Auth**: none (the old `/securities/v1.1/*` gateway now returns
  `Missing Authentication Token` / `SGX_4041`; `financialreports/v1.0`
  is open).
- **Rate limit**: undocumented; conservative 60/min.
- **Coverage**: SGX-listed issuers only. Unlisted Singapore companies
  have **no free financial source** — ACRA BizFile+ Business Profile
  downloads are paid (S$5.50/doc) and excluded from the MVP per the
  non-negotiable "no paid APIs" rule.
- The feed carries no per-report currency or structured line items, so
  `currency`/`structured_data` are left unset (never assumed — Wilmar and
  other issuers report in USD, not SGD). Only filing metadata + the real
  PDF URL are surfaced; if the feed changes shape `fetch_financials`
  returns `[]` rather than guessing.

### What is explicitly excluded (and why)

- **BizFile+ Business Profile** (`bizfile.gov.sg`) — S$5.50 per download,
  paid. Skipped.
- **OpenBizFile name search** — the public BizFile+ name-search form is
  free but session-/CAPTCHA-protected and not a documented API; the open
  ACRA data on data.gov.sg already covers the same registry attributes.

## Test companies

- DBS Group Holdings Ltd — UEN `199901152M` (SGX name `DBS GROUP HOLDINGS LTD`)
- Singapore Telecommunications Limited (Singtel) — UEN `199201624D`
- Wilmar International Limited — UEN `199904785Z` (reports in USD)
- CapitaLand Investment Limited — UEN `200308573K`

Verified live (2026-07): DBS and Wilmar each return search + rich lookup +
3 annual reports (`years=3`) with downloadable PDF URLs.

## Status

Live — `search_by_name` and `lookup_by_identifier` hit the real ACRA
open-data feed via data.gov.sg (no auth, no mock).

Live (listed issuers) — `fetch_financials` returns SGX annual reports with
real filed-PDF URLs for SGX-listed issuers; returns `[]` for unlisted
entities (the spec-compliant outcome — we do not invent data).

**Recommended next steps**:

1. Maintain a name → SGX report index (nightly job) instead of paging the
   full `financialreports` feed per request.
2. Pipe the resolved annual-report PDFs through the planned PDF extraction
   worker (`pypdf` is already in `requirements.txt`) to populate
   `structured_data`.
3. Add an XBRL parser path for SGXNet-filed iXBRL annual reports.
