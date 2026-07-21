# 🇩🇿 Algeria — COSOB / SGBV (+ CNRC / DGI)

## Identifier

- Primary: `OTHER` → **Algiers-exchange market symbol** of a listed
  issuer (e.g. `SAI` = Groupe Saidal, `ALL` = Alliance Assurances,
  `BIO` = Biopharm, `AUR` = EGH El Aurassi, `CPA`, `BDL`, `AOM`, `ALC`,
  `NCA`). This is what `search_by_name` returns and what
  `lookup_by_identifier` / `fetch_financials` consume.
- Secondary: `VAT` → **NIF (Numéro d'Identification Fiscale)**, 15
  digits. Regex `^\d{15}$`; an optional `DZ` prefix is dropped.
- Secondary: `COMPANY_NUMBER` → **RC (Registre de Commerce)** number,
  e.g. `16/00-0123456 B 09`. Permissive alphanumeric/separator check.

## Sources

- **COSOB — Commission d'Organisation et de Surveillance des Opérations
  de Bourse** — https://cosob.dz/emetteurs/informations-financieres/.
  The regulator publishes every listed issuer's filed *états financiers*
  (full annual financial statements) as downloadable PDFs, grouped under
  per-fiscal-year headings. Public, key-free, no bot wall. This is the
  authoritative filings feed and the live issuer directory used for name
  search.
  - **Auth**: None. **Rate limit**: unpublished; adapter throttles to 30/min.
- **SGBV — Bourse d'Alger** — https://www.sgbv.dz/. Per-issuer
  presentation pages (`?page=details_societe&id_soc=N`) carry share
  capital, website, e-mail, phone and the legal presentation. Used to
  enrich `lookup_by_identifier` for the main-market issuers. Pages are
  ISO-latin/UTF-8/entity-mixed; the adapter normalises on read.
- **CNRC — Sidjilcom** — https://sidjilcom.cnrc.dz/. The
  merchant/denomination/social-account searches redirect to
  `/c/portal/login` — a registered account is required, and no free JSON
  contract is published. Not used.
- **DGI — Direction Générale des Impôts** — https://www.mfdgi.gov.dz/.
  NIF validator behind a session-gated HTML form; no free JSON. Not used.

## Test companies

- **Groupe Saidal** — symbol `SAI`; state pharma; états financiers 2010→2024.
- **Alliance Assurances** — symbol `ALL`; insurer.
- **Biopharm** — symbol `BIO`; pharma group.
- **EGH El Aurassi** — symbol `AUR`; hotel operator.

## Status

🟢 **OK** — search, lookup and financials all return real live data,
key-free, for the Algiers-exchange listed universe.

**Capabilities**
- `search_by_name` — scrapes the live COSOB filings directory, maps each
  issuer to its market symbol, returns `CompanyMatch` list (id = symbol).
- `lookup_by_identifier(OTHER, symbol)` — returns `CompanyDetails`
  (name, legal form, share capital in DZD, website/e-mail/phone) enriched
  from the SGBV issuer page for main-market symbols.
- `lookup_by_identifier(VAT|COMPANY_NUMBER, …)` — normalises then raises
  `AdapterNotImplementedError`: CNRC/DGI are login-gated, no free API.
- `fetch_financials(symbol, years=N)` — returns up to N most-recent
  annual `FinancialFiling`s from COSOB (year, `ANNUAL_REPORT`, currency
  `DZD`, `document_url` = a PDF that truly downloads, `source_url`). A
  well-formed NIF/RC that is not a listed issuer returns `[]` (a
  non-listed Algerian SPA/SARL files no public accounts).

**Known gaps / next steps**
- Non-listed companies have no free machine-readable source (CNRC/DGI
  require a registered login). Only the ~10 Algiers-exchange issuers are
  covered.
- Wire the `pypdf` extraction pipeline so the COSOB états-financiers PDFs
  populate `pdf_text_excerpts` for the LLM (statements mix French/Arabic).
- COSOB also posts half-year statements ("premier semestre"); these are
  skipped by `fetch_financials`, which returns annual filings only.
