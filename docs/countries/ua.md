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

Ukraine has no free centralized annual-report dataset for the general
population, but the NSSMC securities-disclosure system does expose the
filed reports of every **securities issuer** for free:

- SMIDA (https://smida.gov.ua) — the issuer profile lives at
  `/db/prof/{edrpou}` and its filed regular reports are served from the
  AJAX fragment `/db/prof/tabs/{edrpou}/regularXml`. That fragment lists
  each filing with `date | year | quarter | type | view-link`; annual
  filings carry the type `Річна` and a per-company viewer URL
  `/db/emitent/report/year/xml/show/{id}`.
- `fetch_financials` fetches that fragment (plain httpx — SMIDA is not
  Cloudflare-walled), parses the annual rows, and returns one
  `FinancialFiling` per year (`ANNUAL_REPORT`, `currency=UAH`,
  `document_url` = the real per-company filing page,
  `source_url` = the issuer profile). No numbers are fabricated —
  `structured_data` is left null; the viewer URL is a genuine link to
  that company's filed report.
- Coverage note: the `regularXml` system holds the statutory "regular
  information" filings (~2012–2018); post-2018 regulated disclosure moved
  to the cabinet system on stockmarket.gov.ua. Historical annual reports
  remain live and per-company.
- General LLC/JSC accounts (non-issuers) are filed with the State Tax
  Service but are not publicly searchable, so `fetch_financials` returns
  `[]` for companies without a SMIDA issuer profile.
- Paid mirrors (YouControl, Opendatabot) wrap the same source.

## Test companies

- Naftogaz of Ukraine — EDRPOU `20077720`
- Ukrnafta — EDRPOU `00135390`
- PrivatBank — EDRPOU `14360570`
- Ukrposhta — EDRPOU `21560045`

## Status

✅ **Live** (2026-07-21, re-verified) — search + lookup via Clarity Project
HTML with FlareSolverr bot-wall bypass (origin serves HTTP 403 to naked
clients; FlareSolverr at `http://127.0.0.1:8191` clears the challenge);
directors/KVED reduced vs. the old JSON API.
✅ Financials: SMIDA regular annual reports for securities issuers
(verified live for EDRPOU `20077720` Naftogaz and `00135390` Ukrnafta —
3 annual filings each). The `document_url` filing viewer was confirmed
company-specific (the page for report id `116448` embeds EDRPOU `20077720`,
the Naftogaz name and the `2017` reporting year). Non-issuers return `[]`
(no free national dataset).

**Recommended next step:** Subscribe nightly to the data.gov.ua YeDR
dump as a fallback when Clarity Project is unreachable, and add a parser
for the post-2018 cabinet disclosure system on stockmarket.gov.ua to pick
up recent-year balance sheets (SMIDA `regularXml` tops out ~2018).
