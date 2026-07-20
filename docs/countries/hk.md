# 🇭🇰 Hong Kong — HKEXnews (listed issuers) + optional OpenCorporates

## Identifiers

- `COMPANY_NUMBER` —
  - **HKEX Stock Code** (key-free path), 5-digit zero-padded, e.g.
    `00700` = Tencent, `00005` = HSBC Holdings, `01299` = AIA Group,
    `00001` = CK Hutchison. This is the free unique identifier for HK
    **listed** issuers.
  - **CR Number** (ICRIS Companies Registry, 7-digit) is also accepted by
    `lookup_by_identifier` / `fetch_financials` **only** when
    `OPENCORPORATES_API_KEY` is set — ICRIS itself is not free-scrapeable.
- `OTHER` — **BR Number** (Business Registration, IRD), 8 digits. IRD's
  BR Number Enquiry is paid; accepted for normalization but
  `lookup_by_identifier(OTHER, …)` raises `AdapterNotImplementedError`
  rather than fabricating a CR↔BR mapping.

## Sources

### Primary (key-free) — HKEXnews
The Companies Registry (ICRIS / e-Services Portal) has **no free public
API** — full extracts are HK$8/doc behind a CSRF/SPA front-end (see the
"blocked" note below). HKEXnews, the Stock Exchange's public disclosure
portal, exposes two stable JSON endpoints that need **no key**:

- **Autocomplete** — resolves a company name or stock code to the
  issuer's internal `stockId`, 5-digit `code` and short `name`:
  `https://www1.hkexnews.hk/search/prefix.do?callback=c&lang=EN&type=A&name={q}&market=SEHK`
  Returns JSONP `c({"stockInfo":[{"stockId":7609,"code":"00700","name":"TENCENT"}]})`.
  Powers `search_by_name` and `lookup_by_identifier`.
- **Title search servlet** — the per-issuer filing list with real PDF
  links:
  `https://www1.hkexnews.hk/search/titleSearchServlet.do?...&market=SEHK&stockId={id}&title=Annual%20Report&fromDate=YYYYMMDD&toDate=YYYYMMDD&searchType=1&lang=EN`
  Returns `{"result":"[{…,\"TITLE\":\"ANNUAL REPORT 2023\",\"FILE_LINK\":\"/listedco/.../…pdf\"}]"}`.
  Filtered to `Annual Report`, this is the source for `fetch_financials`.
  The `FILE_LINK` resolves to a real `application/pdf` (verified: Tencent
  FY2023 ≈ 5.8 MB, HSBC FY2024 ≈ 12 MB).

Coverage: HK **listed issuers** (SEHK main board). Human-facing per-issuer
page: `https://www1.hkexnews.hk/search/titlesearch.xhtml?...&stockCode={code}`.

### Optional (key-gated) — OpenCorporates HK mirror
- `https://api.opencorporates.com/v0.4/companies/hk/{cr}` (free tier: 500
  req/month, `OPENCORPORATES_API_KEY`).
- Used only to (a) look up an ICRIS **CR number** and (b) resolve a CR
  number to a HKEX stock code for `fetch_financials`. Without the key the
  adapter is fully functional for listed issuers via stock code; CR-number
  requests return `None` / raise rather than fabricating data.

## Auth & limits

- **No API key required** for the primary path — search, lookup and
  financials all work key-free for HK listed issuers.
- `OPENCORPORATES_API_KEY` — optional; only unlocks ICRIS CR-number
  lookups.
- Throttled to **30 req/min** (`rate_limit_per_minute = 30`) to be polite
  to HKEXnews.
- robots.txt / ToS: HKEXnews permits read-only access to the public
  disclosure site; ICRIS paid extracts are never touched.

## Test companies (REAL)

- Tencent Holdings Ltd. — HKEX `00700` (CR `0654177`).
- HSBC Holdings plc — HKEX `00005` (CR `0013977`).
- AIA Group Ltd. — HKEX `01299` (CR `1299985`).
- CK Hutchison Holdings — HKEX `00001` (CR `0001392`).

Verified live (July 2026): `search_by_name("Tencent")` → `00700 TENCENT`;
`lookup_by_identifier(COMPANY_NUMBER, "00700")` → `TENCENT`, listed;
`fetch_financials("00700", years=3)` → FY2023/2024/2025 annual-report PDFs.

## Status

✅ **Live (key-free)** — `search_by_name`,
   `lookup_by_identifier(COMPANY_NUMBER = stock code)` and
   `fetch_financials` (real annual-report PDFs) for HK listed issuers via
   HKEXnews, no API key needed.
🟡 **Optional (key-gated)** — ICRIS **CR-number** lookup and CR→stock-code
   resolution require `OPENCORPORATES_API_KEY` (free tier).
🔒 **Blocked (paid)** — full ICRIS extracts, BR-number IRD lookup, and
   unlisted-company financials sit behind paid HK Government gateways and
   are out of scope for the MVP.

**Recommended next step:** wire a Celery PDF-text worker so the annual-
report `document_url` (already a real PDF) is extracted and passed to the
LLM via `pdf_text_excerpts`; and add a GEM-market (`market=GEM`) pass to
`_prefix_search` so GEM-listed issuers are covered alongside SEHK.
