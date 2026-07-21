# 🇦🇿 Azerbaijan — State Tax Service register + Baku Stock Exchange filings

## Identifier

- Type: `VAT`
- Format: **VÖEN** (Vergi Ödəyicisinin Eyniləşdirmə Nömrəsi) — 10 digits.
  Sometimes written with an `AZ` prefix; the adapter strips it. The same
  number serves as the VAT registration ID and the corporate tax ID.

## Sources

- **Company register (name search + VÖEN lookup)** —
  `POST https://new.e-taxes.gov.az/api/po/authless/public/v1/authless/findTaxpayer`
  with body
  `{"tin"|"name": "...", "type": "legalEntity", "serviceCode": "checkLegalName", "isStateRegistry": true}`.
  This JSON endpoint backs the "Kommersiya qurumlarının dövlət reyestri
  məlumatlarının verilməsi" service on the new e-taxes SPA. Free, no auth,
  no cookie, no key. Returns registered name, legal form, charter capital,
  legal address, legal representative, registration dates and status from
  the State Register of Commercial Entities.
- **Filed financial statements** — Baku Stock Exchange
  (Bakı Fond Birjası, `https://www.bfb.az`). Each listed issuer's audited
  IFRS annual accounts are published as PDFs on `/emitent/{slug}`. The
  AZ-locale issuer slug is a transliteration of the registered Azerbaijani
  name, so the register name maps onto the issuer page. Issuer index:
  `https://www.bfb.az/bazara-baxis`.
- **Legacy (dead)**: `www.e-taxes.gov.az/ebyn/commersialChek.jsp` and the
  `commersialChecker*.jsp` forms now 301-redirect to the `new.e-taxes.gov.az`
  SPA and no longer serve data — replaced by the `findTaxpayer` API above.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — government site, no
  published budget.
- **robots.txt / ToS**: Public taxpayer-verification / market-disclosure
  utilities. We send a clearly identifiable User-Agent and keep volume
  polite.

## Test companies

- SOCAR (State Oil Company of Azerbaijan Republic) — VÖEN `9900003871`
  (register lookup + BSE annual filings)
- Azercell Telecom — VÖEN `9900022721` (register only; not a BSE issuer)
- PASHA Bank — VÖEN `1700767721` (register lookup + BSE annual filings)
- Kapital Bank — VÖEN `9900003611` (register lookup + BSE annual filings)

## Status

🟢 **Live — search, lookup, and financials (listed issuers).**

| Capability  | Status                                                     |
|-------------|------------------------------------------------------------|
| Name search | ✅ Live (e-taxes `findTaxpayer` JSON)                       |
| VÖEN lookup | ✅ Live (e-taxes `findTaxpayer` JSON)                       |
| Financials  | ✅ Live for BSE-listed issuers; `[]` for non-listed         |
| Health      | ✅ Probes SOCAR VÖEN via `findTaxpayer`                     |

## Limitations

- **Financials cover listed issuers only.** Only the ~60 companies listed
  on the Baku Stock Exchange publish audited accounts for free. For a
  taxpayer that is not a BSE issuer, `fetch_financials` returns `[]` (no
  filings available) — Azerbaijan does not publish financial statements
  for non-listed companies through any free portal.
- **Issuer matching is name-based.** BSE issuer pages carry no VÖEN, so
  the adapter maps a register name to the issuer slug via a
  transliteration + prefix-tolerant token similarity (handles the genitive
  endings, e.g. `respublikasının` vs `respublikasi`), scoped so shared
  legal-form words (ASC, MMC, …) cannot drive a false match. Document
  URLs are HEAD-verified as downloadable PDFs before being surfaced.
- **Register returns only headline financials.** `findTaxpayer` exposes
  charter capital and tax debt but not full balance sheets; the deep
  numbers come from the BSE IFRS PDFs, parsed downstream.

## Recommended next steps

1. Wire the BSE annual-report PDFs into the PDF text-extraction pipeline
   so the risk engine gets IFRS figures, not just filing metadata.
2. Also surface BSE semi-annual (`Yarımillik`) and management reports.
3. Cache the BSE issuer index (it changes rarely) to avoid re-fetching
   `/bazara-baxis` on every `fetch_financials` call.
