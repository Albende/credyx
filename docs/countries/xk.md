# 🇽🇰 Kosovo — ARBK (Agjencia për Regjistrimin e Bizneseve të Kosovës)

## Identifier

- Primary type: `COMPANY_NUMBER`
- Format: **Numri Unik i Biznesit (UBI / NRB)** — 8 digits followed by
  a single uppercase letter (e.g. `70123456A`). Issued by ARBK at
  registration; stable for the life of the entity.
- Secondary type: `VAT`
- Format: **Numri Fiskal (NF)** — 9 digits (`\d{9}`). The fiscal
  number is issued by the Tax Administration of Kosovo (ATK) and
  doubles as the VAT registration. Under the EU VAT-prefix convention
  it is rendered `XK` + NF; the adapter strips the prefix when
  present. UBI and NF are distinct numbers and the adapter accepts
  either.

> Note on `XK`: ISO 3166-1 has not formally assigned a code to Kosovo,
> but `XK` is a user-assigned code used by the European Commission, the
> IMF, SWIFT, and most cross-border payments systems. CreditLens uses
> `XK` consistently.

## Sources

- https://arbk.rks-gov.net/ — Kosovo Business Registration Agency,
  operated by the Ministry of Industry, Entrepreneurship and Trade
  (MINT). Public free portal supporting search by business name, UBI,
  or NF. UI in Albanian and Serbian, with partial English.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — government site, no
  published budget.
- **robots.txt / ToS**: arbk.rks-gov.net is a public registry-search
  utility intended for third-party use. The adapter sends a clearly
  identifiable User-Agent and keeps volume polite.

## Test companies

- Raiffeisen Bank Kosovo J.S.C. — among the largest banks in Kosovo;
  used for live-search smoke tests.
- Posta dhe Telekomi i Kosovës Sh.A. (PTK) — state-owned incumbent
  telecom operator.
- Banka Ekonomike Sh.A. — domestic commercial bank.
- ProCredit Bank Kosovo Sh.A. — SME-focused commercial bank.

(Exact UBI/NF values are not committed to the repo; integration tests
search by name and validate result shape rather than asserting a
specific identifier.)

## Status

🟡 **Partial — registry only.**

| Capability   | Status                              |
|--------------|-------------------------------------|
| Name search  | ⚠️ Best-effort HTML scrape          |
| UBI lookup   | ✅ Live (HTML scrape)               |
| NF lookup    | ✅ Live (HTML scrape)               |
| Financials   | ❌ Not published in free form       |
| Health       | ✅ Probes arbk.rks-gov.net          |

## Limitations

- **No public financial statements.** Audited annual accounts for
  larger entities are filed with the Kosovo Financial Reporting
  Council (KKRF / KCFR), but the published archive is PDF-only behind
  a session-bound page and not amenable to bulk machine-readable
  retrieval. `fetch_financials` returns `[]` rather than fabricated
  data.
- **HTML scrape is brittle.** ARBK renders the company card as a
  two-column label/value table; the parser matches labels in Albanian
  (Emri i Biznesit, Statusi, Forma e Biznesit, Numri i Biznesit, Numri
  Fiskal, …), Serbian (Naziv, Stanje, Pravna Forma, …), and English.
  Diacritics (ë, ç, š, đ) are preserved through UTF-8 decoding with
  cp1250 fallback.
- **Search-results page may be JavaScript-driven.** The free search
  endpoint occasionally renders results via client-side JS, in which
  case the adapter returns an empty list. The integration test only
  asserts the call returns a well-formed shape, not that it is
  non-empty.
- **Currency defaults to EUR.** Kosovo unilaterally adopted the euro
  in 2002; capital amounts on ARBK are denominated in EUR.

## Recommended next steps

1. Add a Playwright fallback through
   `packages/adapters/_base/browser.py` (once that infrastructure
   lands) to harden `search_by_name` when ARBK renders results
   client-side.
2. Cross-reference each UBI/NF against GLEIF (very few Kosovo LEIs
   exist) and OpenSanctions on lookup to surface sanctions/PEP hits
   up-front.
3. Investigate whether KKRF / KCFR exposes a structured feed of
   audited annual reports for "subjekt me interes publik" (public-
   interest entities); if so, wire a financials adapter on top.
4. Pull the ATK (Tax Administration) public VAT-validity check as a
   second liveness signal when ARBK is down.
