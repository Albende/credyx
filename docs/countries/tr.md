# 🇹🇷 Türkiye — KAP (Public Disclosure Platform)

## Identifier

- Type: `VKN` (mapped to `IdentifierType.VAT`) and `MERSIS`.
- Format: VKN 10 digits; MERSIS 16 digits (often printed `XXXXXXXXXX-XXXXX-X`).
- `TCKN` (11 digits) is for individuals and is rejected by the adapter.

## Sources

- KAP (Kamuyu Aydınlatma Platformu) — https://www.kap.org.tr/
  **Rebuilt on Next.js in 2025**; the old open JSON feeds
  (`/en/api/memberList`, `/en/api/disclosure-list/{oid}`) are gone (404).
  Current free surfaces used by the adapter:
  - `POST /en/api/search/combined` with JSON
    `{"keyword": ..., "discClass": "ALL", "lang": "en", "channel": "WEB"}`
    — full-text company/fund search. Matches titles and tickers only;
    **tax numbers are not indexed**. The `/en` endpoint only matches
    ASCII-folded text, so the adapter folds Turkish characters
    (ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u) before querying.
  - `GET /en/sirket-bilgileri/ozet/{mkkMemberOid}` — company summary page;
    the RSC flight payload embeds a `memberDetail` JSON object with
    `kapMemberTitle`, `taxNo` (VKN), `taxOffice`, `tradeRegNo`,
    `tradeRegDate`, `paidCapital`, `stockCode`, `cityName`,
    `kapMemberType`. The adapter brace-matches and double-decodes it.
    Fetched through `fetch_with_bot_bypass` in case the WAF tightens
    (plain httpx works today; note the WAF rejects GET query strings
    like `?q=` with status 666).
  - `POST /en/api/disclosure/members/byCriteria` — disclosure query.
    **Max one-year date window per request** (larger spans → HTTP 400
    wrapped in a 500 envelope); the adapter pages backwards in yearly
    windows. `disclosureClass="FR"`, `ruleType="Annual"`,
    `subject="Financial Report"` identify annual financial statements;
    `disclosureIndex` links to `https://www.kap.org.tr/en/Bildirim/{index}`.
  - **Auth**: None. Free.
  - **Rate limit**: Not published; adapter throttles to 60 req/min.
  - **robots.txt / ToS**: Public disclosure data, free to consume.
- MERSIS (https://mersis.ticaret.gov.tr/) — public web search but no
  documented JSON API. Not currently scraped.
- MKK e-Şirket (https://e-sirket.mkk.com.tr/) — JS-only shell, no
  server-rendered data; evaluated and rejected as a VKN index.
- e-Devlet (https://www.turkiye.gov.tr/) — most lookups require a
  Turkish e-ID. Out of scope for the free MVP.

## Test companies

- Türk Hava Yolları (Turkish Airlines) A.O. — KAP member OID
  `4028e4a140f2ed720140f376bebb01a7`, BIST ticker `THYAO`,
  VKN `8760047464` (as published in KAP `memberDetail.taxNo`; trade
  registry no `75184-0`, İstanbul).
- Türkiye Garanti Bankası A.Ş. (Garanti BBVA) — BIST `GARAN`.
- Koç Holding A.Ş. — BIST `KCHOL`.
- Akbank T.A.Ş. — BIST `AKBNK`.

## Status

🟢 **LIVE** (July 2026, adapted to the rebuilt KAP platform) for
BIST-listed companies. Non-listed lookups raise
`AdapterNotImplementedError` (no fabricated fallback).

**Capabilities**
- `search_by_name` — KAP combined search; returns the MKK member OID as
  the company id plus the BIST ticker.
- `lookup_by_identifier` — works with the KAP member OID (32-char hex,
  as returned by search) and yields full details **including the VKN**.
  Raw VKN / MERSIS values can no longer be resolved: the rebuilt KAP
  publishes tax numbers only on per-company pages and its search does
  not index them (verified against `/en` and `/tr` search endpoints, the
  member list page, and the Excel export). Such lookups try the search
  once, then raise `AdapterNotImplementedError` with guidance.
- `fetch_financials` — disclosure query filtered to
  `ruleType="Annual"` + `subject="Financial Report"`; returns
  `Bildirim` document URLs per fiscal year. Currency `TRY`.

**Known gaps / next steps**
- VKN→company resolution needs an external free index (none found:
  GİB e-VD is captcha-gated, MERSIS/e-Şirket have no clean API).
- Non-listed (private) companies: MERSIS HTML scrape — needs
  Playwright + the inspected XHR contract.
- Structured XBRL parsing of KAP financial reports — currently we return
  the disclosure URL only; downstream risk engine extracts ratios from
  the XBRL package when present.
