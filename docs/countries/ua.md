# 🇺🇦 Ukraine — YeDR via Clarity Project

## Identifier

- Primary: `COMPANY_NUMBER` — EDRPOU code (Yedyny derzhavnyy reyestr
  pidpryyemstv ta orhanizatsiy Ukrayiny), 8 digits (legacy state bodies
  may be shorter and are left-padded).
- Also: `VAT` — Ukrainian VAT/individual tax codes (10–12 digits). The
  adapter strips an optional `UA` prefix and resolves to the embedded
  EDRPOU.

## Sources

- Open dataset (XML/JSON dumps):
  https://data.gov.ua/dataset/1c7f3815-3259-45e0-bdf1-64dca07ddc10
- Official live search (HTML, captcha for full data):
  https://usr.minjust.gov.ua/content/free-search
- **Used by this adapter** — Clarity Project (open-data mirror, free
  JSON API, no auth):
  - Search: `https://clarity-project.info/api/search?q={query}&format=json`
  - Detail: `https://clarity-project.info/api/edrpou/{code}?format=json`
- **Auth**: No.
- **Rate limit**: Soft, ~30 req/min recommended. The adapter honors
  `Retry-After` from `get_with_retry`.
- **robots.txt / ToS**: Clarity Project publishes the open-data dump
  under the same CC-BY-style terms as data.gov.ua. Heavy use should be
  cached, not hammered.

## Financials

Ukraine has no free centralized annual-report dataset:

- SMIDA (https://smida.gov.ua) hosts filings for listed issuers only —
  a small population.
- General LLC/JSC accounts are filed with the State Tax Service but are
  not publicly searchable.
- Paid mirrors (YouControl, Opendatabot) wrap the same source.

`fetch_financials` therefore returns `[]` for the overwhelming majority
of companies. Per the MVP rule we do **not** fabricate periods.

## Test companies

- Naftogaz of Ukraine — EDRPOU `20077720`
- Ukrnafta — EDRPOU `00135390`
- PrivatBank — EDRPOU `14360570`
- Ukrposhta — EDRPOU `21560045`

## Status

✅ **Live** — search + lookup via Clarity Project.
⚠️ Financials: limited (no free national dataset).

**Recommended next step:** Subscribe nightly to the data.gov.ua YeDR
dump as a fallback when Clarity Project is unreachable, and add a
SMIDA-specific parser to pick up the ~200 listed-issuer balance
sheets.
