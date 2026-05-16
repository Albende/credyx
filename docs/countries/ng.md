# 🇳🇬 Nigeria — CAC / FIRS / NGX

## Identifier

- Primary: `COMPANY_NUMBER` → RC number (Registration of Companies),
  issued by the Corporate Affairs Commission. Format is 1–10 digits,
  often presented with an `RC` prefix (e.g. `RC208767`). Normalised by
  stripping the prefix, spaces, and dashes.
- Secondary: `VAT` → TIN (Tax Identification Number), 8–14 digits.
  FIRS-issued TINs are typically 10 digits; CAC-issued (JTB) TINs are
  longer. No offline checksum.

## Sources

- **CAC** (Corporate Affairs Commission) public search —
  https://search.cac.gov.ng/ and https://publicsearch.cac.gov.ng/.
  - Free name + RC-number lookup is published, but the results page is
    JavaScript-rendered and the result JSON is fetched by a session-bound
    XHR. A plain `httpx.GET` usually returns the page shell only.
  - Full registry extracts, certified true copies, and corporate filings
    are behind the paid **CAC e-services** portal —
    https://services.cac.gov.ng/.
  - **Auth**: None for the public landing page; account required for the
    full data. Out of scope for the free MVP.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.
- **FIRS** (Federal Inland Revenue Service) TIN validator —
  https://tin.firs.gov.ng/.
  - Partial public TIN verification. The page is HTML and frequently
    session-gated. Used best-effort by `lookup_by_identifier(VAT, tin)`.
  - Non-deterministic responses surface as
    `AdapterNotImplementedError` rather than fabricated data.
- **NGX** (Nigerian Exchange) — https://ngxgroup.com/.
  - Free annual reports for listed issuers, keyed by ticker on each
    issuer page. There is no free RC→ticker resolver, so
    `fetch_financials` returns `[]` for now.

## Test companies

- Dangote Cement Plc — RC `208767`, NGX ticker `DANGCEM`.
- MTN Nigeria Communications Plc — RC `1241300`, NGX ticker `MTNN`.
- Nigerian Breweries Plc — RC `613`, NGX ticker `NB`.
- Zenith Bank Plc — RC `150014`, NGX ticker `ZENITHBANK`.

## Status

🟡 **DEGRADED** — RC and TIN lookups are best-effort against
session-gated public pages; name search is available in principle but the
CAC portal renders results client-side, so most plain GET responses are
empty.

**Capabilities**
- `search_by_name(query)` — Defensive scrape of
  https://publicsearch.cac.gov.ng/. Returns matches when the HTML
  carries inline RC+name pairs; raises `AdapterNotImplementedError`
  when the portal renders only the JS shell.
- `lookup_by_identifier(COMPANY_NUMBER, rc)` — Best-effort GET to the
  CAC public search. Returns a `CompanyDetails` when an identity can be
  parsed; raises `AdapterNotImplementedError` otherwise. Certified
  records require the paid e-services account.
- `lookup_by_identifier(VAT, tin)` — Best-effort GET to the FIRS TIN
  validator; raises if the response is not machine-readable.
- `fetch_financials(rc)` — Returns `[]`. NGX annual reports are public
  per-ticker, but no free RC→ticker resolver exists yet.

**Known gaps / next steps**
- Build a small RC→NGX-ticker fixture (~150 listed issuers) and wire
  `fetch_financials` to enumerate per-issuer annual-report PDFs from
  ngxgroup.com.
- A CAC e-services subscription (Phase-2 paid decision) would unlock
  name search, RC details, and filing history.
- FIRS does not publish a documented TIN API; once they ship one the
  `_lookup_by_tin` path becomes a thin JSON client.
- Once the PDF text-extraction pipeline lands, NGX annual reports plug
  into the existing risk pipeline directly (same shape as UK PDFs).
