# 🇶🇦 Qatar — MoCI + QSE

## Identifiers

- **CR Number** (Commercial Registration) — 4-10 digits issued by the
  Ministry of Commerce and Industry. Mapped to
  `IdentifierType.COMPANY_NUMBER`.
- **TIN** — Tax Identification Number issued by the General Tax
  Authority (GTA). Qatar does not operate a VAT regime today, but the
  TIN slot is the closest contract match and is encoded as
  `IdentifierType.VAT`. The adapter strips an optional `QA` prefix.
- **QSE Ticker** — 2-8 uppercase letters identifying a listed issuer on
  the Qatar Stock Exchange (e.g. `QNBK`, `IQCD`, `ORDS`, `QATI`).
  Accepted by `fetch_financials` as the `company_id` to surface filing
  links; optionally prefixed `QSE:`.

## Sources

- **Ministry of Commerce and Industry (MoCI)** —
  https://www.moci.gov.qa/
  - Public CR / Trade Name lookup pages exist but structured fields are
    gated behind Tawtheeq (Qatari national e-ID) login.
  - **Auth**: Tawtheeq. Free in principle but not accessible from
    outside Qatar without a QID.
  - **Rate limit**: Not published. Adapter throttles to 30 req/min.
  - **robots.txt / ToS**: Disallows automated harvesting of session
    pages.
- **General Tax Authority (GTA) TIN validator** —
  https://www.gta.gov.qa/
  - Form-based TIN check, protected by Google reCAPTCHA. No structured
    JSON returned.
- **Qatar Stock Exchange (QSE)** — https://www.qe.com.qa/
  - Annual reports for listed issuers are published as free PDFs on the
    per-issuer page. The catalogue itself is a client-rendered SPA so
    without a headless browser we can only deep-link to the canonical
    issuer page per ticker.

## Test companies (REAL)

| Company | QSE Ticker | Notes |
|---------|------------|-------|
| Qatar National Bank | `QNBK` | Largest bank in MENA |
| Industries Qatar | `IQCD` | Petrochemicals / steel holding |
| Ooredoo | `ORDS` | Telecoms |
| Qatar Insurance Company | `QATI` | General insurance |

## Status

🟡 **Best-effort financials only.** No free public data source exposes
structured Qatar registry details without Tawtheeq authentication or a
reCAPTCHA bypass.

**Capabilities**

- `search_by_name` — raises `AdapterNotImplementedError`. MoCI name
  search is Tawtheeq-gated; there is no free public JSON.
- `lookup_by_identifier`:
  - `COMPANY_NUMBER` (CR) — validates format then raises
    `AdapterNotImplementedError` (MoCI detail page is Tawtheeq-gated).
  - `VAT` (TIN) — validates format (strips `QA` prefix) then raises
    `AdapterNotImplementedError` (GTA validator is reCAPTCHA-gated).
- `fetch_financials` — for QSE-listed tickers returns one
  `FinancialFiling` per year linking to the public QSE issuer page; for
  CR-shaped identifiers returns `[]` (no free unlisted financial
  source); for junk input raises `InvalidIdentifierError`.

**Known gaps / next steps**

1. Headless-browser scrape of QSE issuer pages once
   `packages/adapters/_base/browser.py` lands — annual reports are
   public PDFs but the catalogue is rendered client-side.
2. Cross-reference Qatari entities against the global GLEIF (LEI) feed
   for LEI-bearing issuers (banks, listed companies) as a free
   enrichment layer.
3. Investigate Qatar Financial Centre (QFC) — https://www.qfc.qa/ —
   which operates a separate registry for QFC-licensed firms; the
   public register page is searchable but again client-rendered.
