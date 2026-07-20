# 🇶🇦 Qatar — GLEIF + QSE

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

- **GLEIF (Global LEI Foundation)** — https://api.gleif.org/api/v1
  - Free, no key, JSON:API. Indexes every LEI-holding Qatari entity
    (listed issuers, banks, funds, regulated + W.L.L. firms) with the
    registered legal name, address, legal form, and the MoCI Commercial
    Registration number in `entity.registeredAs`.
  - Drives QA-scoped `search_by_name` (full-text) and CR
    `lookup_by_identifier` (`filter[entity.registeredAs]=<CR>`).
  - **Coverage caveat**: LEI holders only — non-LEI companies are not
    indexed and return `None` on CR lookup.
- **Qatar Stock Exchange (QSE)** — https://www.qe.com.qa/
  - `/wp/mw/data/MarketWatch.txt` — free, no-key JSON snapshot of every
    listed security (`Symbol`, `CompanyEN`, sector). Powers the listed
    company slice of `search_by_name`.
  - `/qdisclosure/api/XBRL/GetFSAttachmentAPI?attachmentType={1|3}&symCode={ticker}&reportEndDate={YYYY-MM-DD}&lang=1`
    — returns the actual filed financial-statement **PDF** for a listed
    issuer and a given quarter-end (`attachmentType=1` detailed audited
    accounts, `3` XBRL-derived). Real filings, not a landing page; a
    missing report returns HTTP 404 JSON. Powers `fetch_financials`.
- **Ministry of Commerce and Industry (MoCI)** —
  https://www.moci.gov.qa/ — public CR / Trade Name lookup is gated
  behind Tawtheeq (national e-ID); no free public JSON. Superseded for
  our purposes by GLEIF's `registeredAs` mapping.
- **General Tax Authority (GTA) TIN validator** —
  https://www.gta.gov.qa/ — reCAPTCHA-gated form; no structured JSON.
  `VAT` (TIN) lookup therefore raises `AdapterNotImplementedError`.

## Test companies (REAL)

| Company | QSE Ticker | CR (GLEIF) | Notes |
|---------|------------|------------|-------|
| Qatar National Bank | `QNBK` | `21` | Largest bank in MENA; FS PDFs 2023-2025 verified |
| Industries Qatar | `IQCD` | — | Petrochemicals / steel holding |
| Ooredoo | `ORDS` | — | Telecoms |
| Qatar Insurance Company | `QATI` | — | General insurance |
| Apex Healthcare W.L.L | — | `151033` | Non-listed, LEI holder — CR lookup test |

## Status

🟢 **Working.** Search, CR lookup, and financials all return real live
data with no API key.

**Capabilities**

- `search_by_name` — merges QSE listed-company matches (from
  `MarketWatch.txt`, carrying the ticker used by `fetch_financials`) with
  GLEIF full-text QA-scoped results (carrying the CR/LEI). Raises
  `AdapterNotImplementedError` only when nothing matches.
- `lookup_by_identifier`:
  - `COMPANY_NUMBER` (CR) — resolves the CR via GLEIF
    `entity.registeredAs` to a full `CompanyDetails` (name, legal form,
    address, LEI). Returns `None` for CRs with no LEI record.
  - `VAT` (TIN) — validates format (strips `QA` prefix) then raises
    `AdapterNotImplementedError` (GTA validator is reCAPTCHA-gated; no
    free source indexes TINs).
- `fetch_financials` — for a QSE ticker, probes the q-disclosure FS API
  for each year-end in range and returns a `FinancialFiling` per year
  whose `document_url` is the real audited financial-statement PDF that
  actually downloads (`application/pdf`, verified before emission). For
  CR-shaped identifiers returns `[]` (no free unlisted financial
  source); for junk input raises `InvalidIdentifierError`.

**Known gaps / next steps**

1. CR lookup covers LEI holders only; full MoCI CR coverage still needs
   Tawtheeq and is out of scope for a free MVP.
2. `fetch_financials` currently emits annual (year-end) filings; the same
   endpoint also serves quarterly reports (`reportEndDate` = `-03-31`,
   `-06-30`, `-09-30`) if interim data is later required.
3. Wire the PDF text-extraction pipeline so the audited-accounts PDFs
   feed structured figures into the risk engine (`pdf_text_excerpts`).
