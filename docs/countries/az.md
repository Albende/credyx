# 🇦🇿 Azerbaijan — DSX (State Tax Service) commercial taxpayer check

## Identifier

- Type: `VAT`
- Format: **VÖEN** (Vergi Ödəyicisinin Eyniləşdirmə Nömrəsi) — 10 digits.
  Sometimes written with an `AZ` prefix; the adapter strips it. The same
  number serves as the VAT registration ID and the corporate tax ID.

## Sources

- https://www.e-taxes.gov.az/ebyn/commersialChek.jsp?vergi_id={voen}
  — public per-VÖEN HTML lookup, free, no auth.
- https://e-taxes.gov.az/ebyn/searchTaxPayerByCommersialAction.do
  — internal form action; not relied on (cookie/session-bound).
- stat.gov.az — State Statistics Committee bulletins, no API.
- justice.gov.az — Ministry of Justice; commercial register is **not**
  freely searchable online (NGOs only).
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — government site, no
  published budget.
- **robots.txt / ToS**: `e-taxes.gov.az/robots.txt` is permissive; site
  is a public taxpayer-verification utility. We send a clearly
  identifiable User-Agent and keep volume polite.

## Test companies

- SOCAR (State Oil Company of Azerbaijan Republic) — VÖEN `9900003871`
- Azercell Telecom — VÖEN `9900025301`
- PASHA Bank — VÖEN `1700767721`
- Kapital Bank — VÖEN `9900003611`

## Status

🟡 **Partial — lookup only.**

| Capability  | Status               |
|-------------|----------------------|
| Name search | ❌ Not implemented   |
| VÖEN lookup | ✅ Live (HTML scrape) |
| Financials  | ❌ Not published     |
| Health      | ✅ Probes SOCAR VÖEN |

## Limitations

- **No public name search.** e-taxes only resolves a known VÖEN. The
  adapter raises `AdapterNotImplementedError` on `search_by_name`. A
  follow-up could integrate OpenCorporates' free AZ tier for fuzzy
  name → VÖEN resolution.
- **No public financial statements.** Annual accounts are filed with
  the Ministry of Finance but are not exposed via a free portal.
  Listed-issuer reports live on the Baku Stock Exchange (BSE) site as
  PDFs only — out of scope for the free MVP. `fetch_financials` raises
  `AdapterNotImplementedError`.
- **HTML scrape is brittle.** The commersialChek.jsp page renders a
  two-column table with localized labels (Azerbaijani Latin script,
  occasionally Cyrillic for Russian-set legacy records). The parser
  matches loosely on both. Encoding fallback covers UTF-8 and
  windows-1251.
- **No clean encoding header.** e-taxes has historically served pages
  without a `charset` declaration; the adapter decodes UTF-8 first,
  then cp1251 to keep diacritics intact.

## Recommended next steps

1. Wire a free name → VÖEN bridge through OpenCorporates AZ.
2. Once a Baku Stock Exchange (BSE) document scraper exists, surface
   listed-issuer PDFs through `fetch_financials` for the ~20 traded
   companies.
3. Investigate whether DSX exposes a structured XML feed under e-Devlet
   for licensed integrators — if so, swap the HTML scrape for it.
