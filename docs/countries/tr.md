# 🇹🇷 Türkiye — KAP (Public Disclosure Platform)

## Identifier

- Type: `VKN` (mapped to `IdentifierType.VAT`) and `MERSIS`.
- Format: VKN 10 digits; MERSIS 16 digits (often printed `XXXXXXXXXX-XXXXX-X`).
- `TCKN` (11 digits) is for individuals and is rejected by the adapter.

## Sources

- KAP (Kamuyu Aydınlatma Platformu) — https://www.kap.org.tr/
  - `GET /en/api/memberList` — every BIST-listed company.
  - `GET /en/api/disclosure-list/{memberOid}` — full disclosure stream
    (annual/interim financial reports, ad-hoc material events).
  - **Auth**: None. Free.
  - **Rate limit**: Not published; adapter throttles to 60 req/min.
  - **robots.txt / ToS**: Public disclosure data, free to consume.
- MERSIS (https://mersis.ticaret.gov.tr/) — public web search but no
  documented JSON API. Not currently scraped.
- e-Devlet (https://www.turkiye.gov.tr/) — most lookups require a
  Turkish e-ID. Out of scope for the free MVP.

## Test companies

- Türk Hava Yolları (Turkish Airlines) A.O. — VKN `0710001297`, BIST ticker `THYAO`.
- Türkiye Garanti Bankası A.Ş. (Garanti BBVA) — VKN `3900296101`, BIST `GARAN`.
- Koç Holding A.Ş. — VKN `5650043812`, BIST `KCHOL`.
- Akbank T.A.Ş. — VKN `0240005009`, BIST `AKBNK`.

## Status

🟢 **LIVE** for BIST-listed companies via KAP. Non-listed lookups raise
`AdapterNotImplementedError` (no fabricated fallback).

**Capabilities**
- `search_by_name` — substring match against KAP `memberList`.
- `lookup_by_identifier` — VKN or MERSIS resolved against KAP members;
  MERSIS matches use the leading 10-digit VKN prefix when KAP does not
  expose the full MERSIS string.
- `fetch_financials` — KAP disclosures filtered for annual ("yıllık")
  reports; returns XBRL document URLs per fiscal year. Currency `TRY`.

**Known gaps / next steps**
- Non-listed (private) companies: MERSIS HTML/AngularJS scrape — needs
  Playwright + the inspected XHR contract.
- Structured XBRL parsing of KAP financial reports — currently we return
  the disclosure URL only; downstream risk engine extracts ratios from
  the XBRL package when present.
