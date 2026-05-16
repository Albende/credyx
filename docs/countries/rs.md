# 🇷🇸 Serbia — APR (Agencija za privredne registre)

## Identifiers

- `COMPANY_NUMBER` → **Matični broj (MB)** — 8 digits. Primary.
- `VAT` → **PIB** — 9 digits (sometimes prefixed `RS` in cross-border VAT
  contexts; we strip the prefix on input).

Examples: NIS a.d. — MB `20084693`, PIB `104052135`.

## Sources

- **APR unified entity search**
  `https://pretraga2.apr.gov.rs/unifiedentitysearch/Search/Search?text=<query>`
  Free, no auth. Server-rendered HTML; accepts company name, MB, or PIB
  as a single free-text query. Returns both Cyrillic and Latin Serbian.
- **APR public financial-statements search**
  `https://pretraga2.apr.gov.rs/fiPublicSearch/SearchEntities/Search?maticniBroj=<mb>`
  Free, no auth. Lists every filed annual financial report
  ("Godišnji finansijski izveštaj") by year, with per-year PDF links.
- **Belgrade Stock Exchange** (now `bgdx.rs`, formerly `belex.rs`) —
  per-issuer profile pages for listed companies; no machine-readable
  filings index, no per-filing JSON. Out of scope for MVP — APR already
  covers listed issuers' filings.

**Auth**: None.
**Rate limit**: Soft. We throttle to 30 req/min to stay conservative.
**robots.txt / ToS**: APR data is public; the portal is intended for
public lookups. We send a descriptive User-Agent and back off on 429.

## Adapter capabilities

| Capability         | Status | Notes                                              |
|--------------------|--------|----------------------------------------------------|
| `search_by_name`   | ✅      | Best-effort HTML scrape of pretraga2 results.      |
| `lookup_by_identifier` | ✅  | By MB (COMPANY_NUMBER) or PIB (VAT).               |
| `fetch_financials` | 🟡     | Discovers reporting years from fiPublicSearch; PDF |
|                    |        | URLs not yet wired (filings list only).            |

## Test companies (real)

| Company              | MB         | PIB         |
|----------------------|------------|-------------|
| NIS a.d. Novi Sad    | 20084693   | 104052135   |
| Telekom Srbija a.d.  | 17162543   | 100002887   |
| Komercijalna banka   | 07737068   | 100001931   |
| Delta Holding d.o.o. | 17073677   | —           |

## Implementation notes

- APR's portal is ASP.NET-rendered HTML. There is no documented JSON
  contract; the parser tolerates either a single-record detail table or
  a multi-row card list, and falls back to scanning plain text for MB /
  PIB tokens. No fabricated fields — if the markup shifts beyond the
  fallback, lookups return `None` rather than invented data.
- Encoding: the portal serves UTF-8 today but historically swapped
  between cp1250 and UTF-8; the adapter tries UTF-8 first and falls back
  through cp1250 / windows-1250 / cp1251.
- Status is normalized to `active` / `ceased` from Cyrillic and Latin
  variants (`Активно`, `Aktivno`, `Брисан`, `Stečaj`, …).
- Currency: Serbian capital is filed in RSD; we report `RSD` unless the
  capital row explicitly mentions EUR.

## Status

🟢 **Live** — search, lookup, and a financials-discovery feed against
the free APR portal. PDF retrieval for individual annual reports is a
follow-up.

**Recommended next step:** parse per-year PDF links out of the
`fiPublicSearch` results table and surface them as `document_url` on
each `FinancialFiling`.
