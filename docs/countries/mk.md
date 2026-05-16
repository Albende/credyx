# 🇲🇰 North Macedonia — Central Registry (CRM) + Macedonian Stock Exchange

## Identifiers

- **EMBS** (Embeded Subject Number) — 7 digits, the Central Registry's
  primary key for every legal entity. Maps to
  `IdentifierType.COMPANY_NUMBER`. Inputs shorter than 7 digits are
  left-zero-padded.
- **EDB** (Edinstven daneken broj) — 13-digit tax identifier issued by
  UJP (Public Revenue Office). Legal entities typically start with the
  regional prefix `4030` or `4080`. Maps to `IdentifierType.VAT`. The
  optional `MK` country prefix is stripped on normalization.

## Sources

### Registry — Central Registry of North Macedonia (CRM)

- Marketing site: <https://www.crm.com.mk/>
- Public free search portal: <https://e-submit.crm.com.mk/>
- Returns: name, EMBS, EDB, address, legal form, status, principal NACE
  code, and registered share capital. Renders Macedonian Cyrillic with
  occasional Latin transliteration.
- **Auth**: none.
- **Rate limit**: 30 req/min (self-imposed; no documented hard limit).
- **ToS / robots.txt**: open government data; respectful crawler UA only.
- **Format**: server-rendered ASP.NET HTML — no public JSON contract.
  Adapter scrapes conservatively and falls back to flat-text EMBS/EDB
  scanning when the table markup shifts. No fabricated fields.

### Financials — Macedonian Stock Exchange (MSE)

- <https://www.mse.mk/> publishes annual reports for listed issuers free
  of charge. Filings are PDFs; structured (XBRL) filings are not
  available. The adapter surfaces deep-links by reporting year and lets
  the cross-cutting PDF text-extraction worker fetch and excerpt the
  documents (mirrors the UK / Croatia approach).
- For non-listed companies, CRM does not publish annual filings via a
  free public API, so `fetch_financials()` returns `[]`.
- Currency: `MKD`. Denar is pegged to the Euro (~61.5 MKD ≈ 1 EUR).

## Test companies

- Komercijalna Banka AD Skopje — EMBS `4068916`, EDB `4030996115218`
- Alkaloid AD Skopje — EMBS `4029895`, EDB `4030995188039`
- Makedonski Telekom AD — EMBS `5807950`
- NLB Banka AD Skopje — EMBS `4067127`

## Status

🟡 **PARTIAL** — registry search + lookup live via CRM portal scrape;
filings limited to MSE-listed issuers as PDF deep-links per year. CRM's
e-submit pages occasionally serve a JS-only shell, in which case the
adapter returns `None` from lookups (never mocks). Structured / XBRL
financials are not available from a free source — a paid InfoCamere-class
provider would be required for a Phase-2 upgrade.
