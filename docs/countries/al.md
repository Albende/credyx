# 🇦🇱 Albania — National Business Center (QKB / QKR)

## Identifier

- Primary type: `VAT`
- Format: **NIPT** (Numri i Identifikimit te Personit te Tatueshëm) — 10
  characters in the canonical `L\d{8}L` shape (leading letter + 8
  digits + trailing letter, e.g. `J91904005U`). The taxpayer ID
  doubles as the VAT registration number; under the EU prefix
  convention it is written `AL` + NIPT — the adapter strips that
  prefix when present.
- Secondary type: `COMPANY_NUMBER` — also the NIPT. Albania uses a
  single registry number across QKB and DPT, so both identifier types
  accept the same value.

## Sources

- https://www.qkb.gov.al/ — Qendra Kombëtare e Biznesit (National
  Business Center), the unified Albanian commercial registry under the
  Ministry of Economy. Free, no auth. Supports per-company lookup by
  NIPT or by name. Albanian-language UI with an English toggle.
- https://www.tatime.gov.al/ — General Directorate of Taxes (DPT).
  Hosts a NIPT validator used here as a liveness probe and a soft
  fallback when QKB markup changes.
- https://www.bse.com.al/ — Bursa e Tiranës (Tirana Stock Exchange).
  Single-digit listed issuers with PDF-only filings — out of scope for
  the free MVP.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — government site, no
  published budget.
- **robots.txt / ToS**: qkb.gov.al is a public registry-search
  utility intended for third-party use. The adapter sends a clearly
  identifiable User-Agent and keeps volume polite.

## Test companies

- ONE Telecommunications (ex Telekom Albania Sh.A.) — NIPT `J91904005U`
- Banka Kombëtare Tregtare Sh.A. (BKT) — NIPT `J61824032O`
- Albtelecom Sh.A. — NIPT `J92013004M`
- Vodafone Albania Sh.A. — NIPT `J81701045S`

## Status

🟡 **Partial — registry only.**

| Capability   | Status                          |
|--------------|---------------------------------|
| Name search  | ⚠️ Best-effort HTML scrape      |
| NIPT lookup  | ✅ Live (HTML scrape)            |
| Financials   | ❌ Not published in free form    |
| Health       | ✅ Probes qkb.gov.al             |

## Limitations

- **No public financial statements.** Annual accounts (Pasqyra
  Financiare) are filed with QKB but are exposed only as scanned PDFs
  behind a session-bound page and on a per-document fee basis through
  the historical archive. Bursa e Tiranës PDFs are out of scope for
  the free MVP. `fetch_financials` returns `[]` rather than fabricated
  data.
- **HTML scrape is brittle.** qkb.gov.al renders the company card as
  a two-column label/value table; the parser matches labels in both
  Albanian (Emri i subjektit, Statusi, Forma ligjore, NIPT, …) and
  English. Diacritics (ë, ç) are preserved through UTF-8 decoding.
- **Search-results page may be JavaScript-driven.** The free search
  endpoint occasionally renders results via client-side JS, in which
  case the adapter returns an empty list. The integration test only
  asserts the call returns a well-formed shape, not that it is
  non-empty.
- **Capital amounts default to ALL** (Albanian lek). Some recent
  filings denominate in EUR; the raw value is preserved in
  `CompanyDetails.raw.fields.capital` so the risk engine can re-parse
  if needed.

## Recommended next steps

1. Add a Playwright fallback through `packages/adapters/_base/browser.py`
   (once that infrastructure lands) to harden `search_by_name` when
   QKB renders results client-side.
2. Wire the future `pypdf` pipeline to extract Bursa e Tiranës issuer
   reports — covers the handful of listed Albanian companies.
3. Cross-reference each NIPT against GLEIF and OpenSanctions on lookup
   to surface LEI links and PEP/sanctions hits up-front.
4. Investigate whether DPT exposes a structured JSON endpoint for
   licensed integrators (would let us swap the brittle HTML scrape).
