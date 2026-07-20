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
- **Used by this adapter** — Clarity Project (open-data mirror). Its old
  free JSON API (`/api/search`, `/api/edrpou/{code}`) was removed in 2026
  (404 from the origin) and the whole site now sits behind a hard
  Cloudflare challenge, so the adapter parses the server-rendered HTML
  through `fetch_with_bot_bypass` (plain httpx first, FlareSolverr
  fallback — requires the `creditlens-flaresolverr` container / a
  reachable `FLARESOLVERR_URL`):
  - Search: `https://clarity-project.info/edrs?query={query}`
  - Detail: `https://clarity-project.info/edr/{code}`
- **Auth**: No account, but Cloudflare bot-wall — FlareSolverr needed for
  datacenter/naked clients.
- **Rate limit**: Soft, ~30 req/min recommended; each FlareSolverr
  round-trip is slow (~5–15 s), which throttles naturally.
- **robots.txt / ToS**: Clarity Project publishes the open-data dump
  under the same CC-BY-style terms as data.gov.ua. Heavy use should be
  cached, not hammered.
- Notes on parsed fields: name (h1 / `Назва`), legal form
  (`Організаційна форма`), status (`Стан`), registration date
  (`Дата реєстрації`), charter capital (`Статутний капітал`), director
  (`Керівник`). Addresses are partially masked (`***`) for anonymous
  sessions; the adapter keeps the visible parts. KVED codes are
  lazy-loaded by the frontend and not available from the static page.
- Evaluated alternatives (July 2026): ring.org.ua (origin dead, 522),
  usr.minjust.gov.ua (unreachable/captcha), opendatabot & YouControl
  (paid), data.gov.ua (bulk dumps only).

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

✅ **Live** (July 2026, re-verified) — search + lookup via Clarity Project
HTML with FlareSolverr bot-wall bypass; directors/KVED reduced vs. the old
JSON API.
⚠️ Financials: limited (no free national dataset).

**Recommended next step:** Subscribe nightly to the data.gov.ua YeDR
dump as a fallback when Clarity Project is unreachable, and add a
SMIDA-specific parser to pick up the ~200 listed-issuer balance
sheets.
