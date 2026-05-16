# 🇰🇬 Kyrgyzstan — Ministry of Justice legal-entity register

## Identifier

- Types: `VAT`, `COMPANY_NUMBER`
- Format: **INN** (ИНН — идентификационный налоговый номер) — 14 digits
  for corporate taxpayers. The same number serves as the corporate tax
  ID, the VAT registration ID, and the Min Justice registry primary
  key. Sometimes written with a `KG` prefix or with spaces/dashes; the
  adapter normalizes everything to 14 contiguous digits.

## Sources

- https://register.minjust.gov.kg/register/ — public legal-entity
  register operated by the Ministry of Justice of the Kyrgyz Republic
  (Министерство юстиции). Russian-language search form; per-entity
  HTML detail page keyed by INN. Surfaces name, legal form, status,
  registered address, OKPO, declared charter capital, and the first
  signatory / manager.
- https://sti.gov.kg/ — State Tax Service VAT validator. Partial
  public, session-bound; not relied on by the adapter.
- https://www.kse.kg/ — Kyrgyz Stock Exchange. Limited free coverage
  of listed-issuer disclosures, no per-INN reverse lookup; not wired.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — no published budget.
- **robots.txt / ToS**: register.minjust.gov.kg is a public-disclosure
  utility. We send an identifiable User-Agent and keep volume polite.

## Test companies

- Kyrgyzaltyn OJSC (state gold producer) — `01410199810177`
- Kyrgyz Investment and Credit Bank (KICB) — `02401199810064`
- MegaCom / Alpha Telecom CJSC — `02212200410023`
- Bishkek Mekhanika ALDA OJSC — partial (use as exploratory probe)

## Status

🟡 **Partial — search + lookup; no financials.**

| Capability      | Status                |
|-----------------|-----------------------|
| Name search     | ✅ Live (HTML scrape) |
| INN lookup      | ✅ Live (HTML scrape) |
| Financials      | ❌ Not published      |
| Health          | ✅ Probes Kyrgyzaltyn |

## Limitations

- **No centralized free financial dataset.** The Min Justice register
  stores administrative facts only. There is no public balance-sheet
  registry; KSE.kg lists a handful of issuers but exposes no per-INN
  reverse lookup and no machine-readable filings index. `fetch_financials`
  returns `[]` honestly rather than fabricating filings (spec rule 1).
- **HTML scrape is brittle.** The per-company page renders a two-column
  table with Russian (Cyrillic) labels and occasional Kyrgyz/English
  variants. The parser matches loosely on all three. Encoding fallback
  covers UTF-8 and windows-1251.
- **Search uses the public form.** Min Justice exposes no JSON contract;
  the adapter submits the same `?name=` / `?inn=` query parameters the
  search form does and parses the resulting `<a href="...inn=...">`
  anchors. If the page layout changes, callers can still look up known
  INNs directly.
- **No separate company number.** As in most CIS jurisdictions,
  Kyrgyzstan uses a single INN for tax and registry purposes, so both
  `VAT` and `COMPANY_NUMBER` identifier types resolve to the same
  14-digit number. OKPO codes are surfaced as a secondary
  `IdentifierType.OTHER` when the detail page exposes one.

## Recommended next steps

1. Investigate whether the State Tax Service (sti.gov.kg) exposes a
   machine-readable VAT-payer feed that can corroborate Min Justice
   status flags.
2. Bridge name → INN fuzzy search through OpenCorporates' KG tier for
   queries where the register search returns no anchor results.
3. If the National Statistical Committee (stat.kg) ever publishes
   structured financial reporting (currently it ships only aggregate
   PDFs), pipe that into `fetch_financials` via the cross-cutting PDF
   extraction worker.
