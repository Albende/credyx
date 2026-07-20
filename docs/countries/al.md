# 🇦🇱 Albania — OpenCorporates.al (AIS open-data mirror of QKB)

## Identifier

- Primary type: `VAT`
- Format: **NIPT** (Numri i Identifikimit te Personit te Tatueshëm) — 10
  characters in the canonical `L\d{8}L` shape (leading letter + 8
  digits + trailing letter, e.g. `J61814094W`). The taxpayer ID
  doubles as the VAT registration number; under the EU prefix
  convention it is written `AL` + NIPT — the adapter strips that
  prefix when present.
- Secondary type: `COMPANY_NUMBER` — also the NIPT. Albania uses a
  single registry number across QKB and DPT, so both identifier types
  accept the same value.

## Sources

- https://opencorporates.al/ — the primary source. A free, no-auth
  open-data mirror of the Albanian commercial registry (QKB / QKR)
  published by the **Albanian Institute of Science (AIS)** — the same
  civil-society group behind Open Data Albania, Open Spending Albania,
  and Open Procurement Albania. Endpoints used:
  - `GET /sq/search/?name={query}` — name search; returns result cards
    (company name, NIPT link, city).
  - `GET /en/nipt/{NIPT}` — company detail page (English UI). Carries
    the registry record (legal form, status, foundation date, initial
    capital, administrators, scope, addresses) **and** re-published
    filed annual accounts: `Annual Turnover` and `Profit before Tax`
    per year, plus links to the actual filed financial-statement
    documents (`Pasqyra Financiare {year}`, PDF/XLS) hosted on the same
    host under `/documents/bilanci/…`.
- https://www.qkb.gov.al/ — the official QKB portal. Public but exposes
  no machine-readable financials; superseded here by the AIS mirror,
  which republishes the same registry data plus filed accounts.
- **Auth**: None. No API key.
- **Rate limit**: Self-imposed at 30 req/min — courtesy to a
  civil-society host, no published budget.
- **robots.txt / ToS**: opencorporates.al is a public open-data portal
  intended for third-party reuse. The adapter sends a clearly
  identifiable User-Agent and keeps volume polite.

## Test companies

NIPTs below resolve directly on opencorporates.al (verified live).

- ONE ALBANIA (ex Telekom Albania Sh.A.) — NIPT `J61814094W`
- Banka Kombëtare Tregtare Sh.A. (BKT) — NIPT `J62001011Q`
- Vodafone Albania Sh.A. — NIPT `K11715005L`
- Vodafone M-Pesa Sh.A. — NIPT `L31527001N`

> The earlier doc listed `J91904005U` (ONE/Telekom) and `J61824032O`
> (BKT); those NIPTs no longer resolve on the open-data mirror (ONE now
> files under `J61814094W`). Use the values above.

## Status

🟢 **Live — registry + filed annual accounts.**

| Capability   | Status                                             |
|--------------|----------------------------------------------------|
| Name search  | ✅ Live (`/sq/search/` result-card scrape)         |
| NIPT lookup  | ✅ Live (`/en/nipt/{NIPT}` detail scrape)          |
| Financials   | ✅ Live — annual turnover + profit-before-tax per year, with links to filed statement documents |
| Health       | ✅ Probes opencorporates.al detail page            |

## Financials

`fetch_financials` returns one `FinancialFiling` per reported year
(most recent first, capped at `years`). Each filing carries:

- `structured_data`: `annual_turnover` and/or `profit_before_tax` in ALL
  (Albanian lek) — the company's real published figures, never
  fabricated. A year is only emitted when the source page carries a real
  figure or a real document link for it.
- `document_url`: the actual filed statement document
  (`/documents/bilanci/…`, PDF or XLS/XLSX) when the page links one for
  that year; `document_format` is set from the extension.
- `type` = `annual_report`, `currency` = `ALL`, `period_end` =
  31 Dec of the year.

These are the annual accounts as filed with QKB and republished by AIS;
the balance-sheet documents download as real files (verified: ~180 KB
XLS / ~600 KB PDF for sample companies).

## Limitations

- **Mixed page encoding.** Detail pages mix UTF-8 (financial labels,
  most names) with occasional stray Latin-1 accents in free-text fields
  (some legal-form/address strings). The adapter decodes UTF-8 and
  replaces the rare invalid byte, so a handful of `ë`/`ç`/`á` in
  free-text fields may render as `�`. This never affects the NIPT,
  status, dates, capital, or the financial figures — no data is
  fabricated or misattributed.
- **Coverage is registry-wide but not exhaustive.** AIS mirrors QKB but
  a NIPT that is absent from their dataset returns a 404 → `lookup`
  yields `None` and `financials` yields `[]` (never mock data).
- **Turnover/profit only.** The structured figures are top-line
  turnover and profit-before-tax; full balance-sheet line items live
  only inside the linked filing documents (to be mined by the future
  `pypdf` / XLS extraction pipeline).

## Recommended next steps

1. Wire the filing documents (`document_url`) into the `pypdf` / XLS
   extraction pipeline to lift full balance-sheet line items for the
   deterministic ratio engine.
2. Cross-reference each NIPT against GLEIF and OpenSanctions on lookup
   to surface LEI links and PEP/sanctions hits up-front.
3. Consider a smarter per-field encoding repair if the `�` noise in
   free-text fields becomes a display concern.
