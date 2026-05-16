# 🇲🇩 Moldova — ASP / idno.md

## Identifier

- Type: `COMPANY_NUMBER` (IDNO — Identification Number), also acts as `VAT` / cod fiscal.
- Format: 13 digits. The first digit encodes the legal form
  (1 = SRL/SA and similar legal persons).
- Examples: 1003600015304 (Moldovagaz SA), 1002600015173 (Orange Moldova SA).

## Sources

- ASP (Agenția Servicii Publice) — https://asp.gov.md/ —
  state company register. No free REST API; per-document filings are paid.
- https://date.gov.md/ — government open-data portal. Periodic dataset
  dumps only, no live search endpoint.
- https://www.idno.md/ — community HTML directory keyed by IDNO. Free,
  no auth, scraped for name search and per-IDNO lookup.
- https://moldse.md/ — Moldova Stock Exchange. Limited free disclosure
  for the very small number of listed issuers; not wired in MVP.
- **Auth**: None required for the free sources above.
- **Rate limit**: Self-imposed 30 req/min, conservative for an HTML scrape.
- **robots.txt / ToS**: idno.md does not forbid public reading; respect
  `Retry-After` and back off on 429/5xx (handled by `get_with_retry`).
- **Charset**: Pages contain UTF-8 Romanian (Latin) and occasional
  Cyrillic — `httpx` decodes both transparently.

## Test companies

- Moldovagaz SA — `1003600015304`
- Banca de Economii SA — `1002600015429`
- Orange Moldova SA — `1002600015173`
- Moldtelecom SA — `1002600043308`

## Capabilities

| Capability     | Status | Notes |
|----------------|--------|-------|
| `search_by_name`         | ✅ | Scrapes idno.md `/search/?q=…`. |
| `lookup_by_identifier`   | ✅ | Scrapes `/company/{idno}/` detail. |
| `fetch_financials`       | ❌ | No free centralized filings in Moldova. |

## Status

🟡 **Partial** — search + lookup via idno.md scrape, no financials.

**Recommended next steps:**
1. Ingest the periodic ASP open-data dump from `date.gov.md` into Postgres
   so search is independent of idno.md uptime.
2. Wire Moldova Stock Exchange (moldse.md) disclosure feed for listed
   issuers' annual reports — small set but real XBRL/PDF available.
3. If a paid InfoCredit / Vlaicu Credit Bureau integration is approved in
   Phase 2, add a separate adapter behind a feature flag — never replace
   the free path.
