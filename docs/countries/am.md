# 🇦🇲 Armenia — State Register of Legal Entities (e-Register.am)

## Identifier

- Primary type: `VAT`
- Format: **TIN / ՀՎՀՀ** (Hark Vcharoghi Hashvarkayin Hamar) — 8 digits.
  Sometimes prefixed with `AM`; the adapter strips it. The same number
  serves as the VAT registration ID and the corporate tax ID.
- Secondary type: `COMPANY_NUMBER` — the State Registry serial number.
  Variable length, usually rendered in `NN.NNN.NNNNN` form (e.g.
  `290.110.05049`). Whitespace is stripped; otherwise passed through.

## Sources

- https://www.e-register.am/ — public State Register of Legal Entities
  operated by the Ministry of Justice. Free, no auth. Supports
  per-company lookup by TIN or by registry number; pages are served in
  Armenian, Russian, and English.
- https://src.am/ — State Revenue Committee VAT/TIN validator. Partial
  public, session-bound; not relied on by the adapter.
- https://amx.am/ — Armenia Securities Exchange (NASDAQ OMX Armenia).
  Lists ~10 traded equities with PDF-only filings — out of scope for
  the free MVP.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — government site, no
  published budget.
- **robots.txt / ToS**: e-register.am is a public registry-search
  utility intended for third-party use. The adapter sends a clearly
  identifiable User-Agent and keeps volume polite.

## Test companies

- Ardshinbank CJSC — TIN `02525118`
- Ameriabank CJSC — TIN `02501006`
- VivaCell-MTS (K-Telecom CJSC) — TIN `00056358`
- Yerevan Brandy Company (Yerevan Ararat Brandy-Wine-Vodka Factory) —
  TIN `02527032`

## Status

🟡 **Partial — registry only.**

| Capability   | Status                          |
|--------------|---------------------------------|
| Name search  | ⚠️ Best-effort HTML scrape      |
| TIN lookup   | ✅ Live (HTML scrape)            |
| Reg-# lookup | ✅ Live (HTML scrape)            |
| Financials   | ❌ Not published                 |
| Health       | ✅ Probes Ardshinbank TIN        |

## Limitations

- **No public financial statements.** Annual accounts are filed with
  the State Revenue Committee (SRC) but not exposed via a free portal
  for non-listed companies. AMX-listed issuers publish PDF reports
  only — out of scope for the free MVP. `fetch_financials` raises
  `AdapterNotImplementedError`.
- **HTML scrape is brittle.** e-register.am renders the company card
  as a two-column table with labels in Armenian (Unicode), Russian
  (Cyrillic), or English depending on the active site language. The
  parser matches loosely on all three. Encoding fallback covers UTF-8
  and windows-1251.
- **Search-results page may be JavaScript-driven.** The free search
  endpoint occasionally renders results via client-side JS, in which
  case the adapter returns an empty list. The integration test only
  asserts the call returns a well-formed shape, not that it is
  non-empty.
- **Capital amounts are best-effort.** Parsed by stripping currency
  symbols and thousand separators; defaults to `AMD`. Returns `None`
  when the page omits a numeric value.

## Recommended next steps

1. Add a free name → TIN bridge through OpenCorporates AM tier (when
   their Armenian dataset is current) to harden `search_by_name`.
2. Wire an AMX PDF scraper through the future `pypdf` pipeline so the
   ~10 traded issuers expose `fetch_financials` results.
3. Investigate whether the SRC exposes a structured JSON endpoint for
   licensed integrators (would let us swap the brittle HTML scrape).
4. Cross-reference each TIN against GLEIF and OpenSanctions on lookup
   to surface LEI links and PEP/sanctions hits up-front.
