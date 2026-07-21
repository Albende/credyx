# 🇰🇭 Cambodia — GLEIF registry + CSX filings

## Identifier

- Types: `COMPANY_NUMBER`, `VAT`.
- `COMPANY_NUMBER` (primary) — MoC registration number printed on the
  Certificate of Incorporation. Typically 8-digit zero-padded
  (e.g. `00003077`). The adapter accepts 1–10 digits and normalises to
  8 by zero-padding; `KH` prefix and separators (`- . space`) are
  stripped. This is the value GLEIF stores in `entity.registeredAs` for
  Cambodian legal entities.
- `VAT` — Tax Identification Number issued by the General Department of
  Taxation (GDT). 9–10 digits. Best-effort only: resolved via a GLEIF
  full-text probe; there is no free public GDT VAT API today.

## Sources

- **https://api.gleif.org** — Global LEI Foundation index. **Auth**: No.
  Cambodian entities carry their Ministry of Commerce registration
  number in `entity.registeredAs`, plus the English legal name
  (`otherNames` / `ALTERNATIVE_LANGUAGE_LEGAL_NAME`), address, legal
  form (ELF code) and status. The adapter uses:
  - name search — `GET /lei-records?filter[entity.legalAddress.country]=KH&filter[fulltext]={name}`
  - MoC lookup — `GET /lei-records?filter[entity.registeredAs]={moc}`
  Coverage is limited to Cambodian entities that hold an LEI (banks,
  listed issuers, larger firms — ~37 entities as of build).
- **https://csx.com.kh** — Cambodia Securities Exchange website API.
  **Auth**: No. Endpoints (base `/api/v1/website`):
  - `GET /company/stock/list-companies` — the full listed-company
    universe (`symbolEn`, `nameEn`, ISIN `icode`, listing date).
  - `POST /company/stock/annual-reports/{symbol}?page=N` — filed reports
    for an issuer (title, publish date, id).
  - `GET /company/stock/annual-reports/{symbol}/{id}` — report detail
    including `attachFiles` (the PDF file descriptors).
  - `GET /file/view-attach?postId=…&fileName=…&boardLang=en&boardId=…&fileOrder=…&originalFileName=…`
    — streams the actual PDF (`Content-Type: application/pdf`). This is
    the `document_url` emitted on each `FinancialFiling`.
  The adapter resolves a company's CSX symbol by matching its GLEIF
  English name against `list-companies`, then emits one filing per
  distinct reporting year for reports whose title is an annual report.
- No paid sources used (no InfoCamere-style commercial register, no D&B).

## Financials pipeline

1. `fetch_financials(moc)` → GLEIF lookup by `registeredAs` → English name.
2. Name → CSX `symbolEn` via live `list-companies` (exact slug, then
   containment fallback). No match ⇒ `[]` (unlisted; never fabricated).
3. `POST annual-reports/{symbol}` (paginated) → filter titles containing
   "annual report".
4. Per report, `GET annual-reports/{symbol}/{id}` → `attachFiles` →
   English PDF → `view-attach` URL. Year parsed from the report title.

## Test companies

- **ACLEDA Bank Plc.** — MoC `00003077`, CSX `ABC`. Live: search →
  lookup → 3 annual-report PDFs (2025 14.8 MB, 2024 9.2 MB, 2023 6.4 MB).
- **PESTECH (Cambodia) Plc.** — MoC `00000957`, CSX `PEPC`. Live: search
  → lookup → annual-report PDFs.
- **First Finance Plc** — MoC `00016858`. In GLEIF but not CSX-listed →
  financials correctly return `[]`.

## Status

✅ **Live** — name search and MoC-number lookup via GLEIF; financials via
the CSX website API as real, downloadable, company-specific annual-report
PDFs for listed issuers. Unlisted firms return `[]` (the rule: never
fabricate filings for a credit decision). No API key required.

## Known limitations

- GLEIF only covers Cambodian entities that hold an LEI, so name search /
  lookup do not reach the full MoC register. The Ministry of Commerce's
  own `businessregistration.moc.gov.kh` public search (used by earlier
  builds) now returns a maintenance page and serves no data; if/when it
  returns, it can be wired as a broader-coverage primary source.
- Some CSX-listed issuers have no LEI, so their MoC number cannot be
  resolved from GLEIF; those companies are reachable by name search only
  once they appear in GLEIF.
- `VAT` lookup is best-effort (GLEIF full-text) — there is no free public
  GDT VAT API.

## Recommended next step

If MoC restores a public search API, add it as the primary registry
source (broader than GLEIF's LEI-holder subset) and keep GLEIF as the
LEI/enrichment layer. For CSX-listed issuers, wire the PDF text through
the pypdf/Celery pipeline so `pdf_text_excerpts` reach the LLM.
