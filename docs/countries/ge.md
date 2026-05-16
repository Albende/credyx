# 🇬🇪 Georgia — NAPR (National Agency of Public Registry)

## Identifier

- Types: `VAT`, `COMPANY_NUMBER`
- Format: **Identification Number** (საიდენტიფიკაციო ნომერი) — 9 digits.
  The same number serves as the corporate tax ID, the VAT registration
  ID, and the commercial registry primary key. Sometimes written with a
  `GE` prefix; the adapter strips it.

## Sources

- https://enreg.reestri.gov.ge/main.php — bilingual (ქართული / English)
  public business register operated by NAPR. Per-company HTML lookup by
  9-digit Identification Number; name search via the public form.
- https://rs.ge/ — Revenue Service VAT validator (partial public; not
  used by the adapter).
- https://gse.ge/ — Georgian Stock Exchange, limited free coverage of
  listed-issuer disclosures (not wired).
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — no published budget.
- **robots.txt / ToS**: enreg.reestri.gov.ge serves a permissive
  robots policy; the registry is a public-disclosure utility. We send
  an identifiable User-Agent and keep volume polite.

## Test companies

- Bank of Georgia JSC — `204378869`
- TBC Bank JSC — `204854595`
- JSC Telasi — `200032475`
- Wissol Petroleum Georgia — `211302796`

## Status

🟡 **Partial — search + lookup; no financials.**

| Capability      | Status                |
|-----------------|-----------------------|
| Name search     | ✅ Live (HTML scrape) |
| ID lookup       | ✅ Live (HTML scrape) |
| Financials      | ❌ Not published      |
| Health          | ✅ Probes Bank of Georgia |

## Limitations

- **No centralized free financial dataset.** NAPR does not publish
  balance sheets. The Service for Accounting, Reporting and Auditing
  Supervision (saras.gov.ge) operates a reporting portal whose public
  search is captcha-gated and whose documents are PDFs — out of scope
  for the free MVP. `fetch_financials` returns `[]` honestly rather
  than fabricating filings.
- **HTML scrape is brittle.** The per-company page renders a two-column
  table with Georgian (Mkhedruli script) labels and occasional English
  transliterations. The parser matches loosely on both. Encoding
  fallback covers UTF-8 and windows-1251.
- **Search uses the public form.** NAPR exposes no JSON contract; the
  adapter submits the same query parameters the search form does and
  parses the resulting `<a href="...legal_code=...">` anchors. If the
  page layout changes, callers can still look up known IDs directly.
- **No separate company number.** Unlike most EU registries, Georgia
  uses a single 9-digit ID for tax and registry purposes, so both
  `VAT` and `COMPANY_NUMBER` identifier types resolve to the same
  number.

## Recommended next steps

1. Wire a captcha-tolerant client for reportal.saras.gov.ge so the
   ~3,500 mandatory reporters' annual PDFs surface through
   `fetch_financials`.
2. Add a free name → ID fuzzy bridge through OpenCorporates' GE tier
   for queries where the registry search returns no anchor results.
3. Investigate whether NAPR exposes a structured XML or CSV feed under
   data.gov.ge — if so, swap the HTML scrape for it.
