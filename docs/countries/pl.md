# 🇵🇱 Poland — KRS + Biała Lista

## Identifiers

- `KRS` — 10-digit court registry number (primary)
- `NIP` — 10-digit tax id; same number used as the Polish VAT (with a `PL`
  prefix). Treated as both `NIP` and `VAT` in `IdentifierType`.
- `REGON` — 9 or 14-digit statistical id (lookup not implemented; needs the
  GUS BIR API which requires a manually-approved free key).

## Sources

| Purpose | Endpoint | Auth | Notes |
|---------|----------|------|-------|
| Full registry record | `GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json` | none | Falls back to `rejestr=S` (associations) on 404 |
| NIP → KRS / VAT status | `GET https://wl-api.mf.gov.pl/api/search/nip/{nip}?date=YYYY-MM-DD` | none | `date` parameter is required |
| Filings (RDF) | `https://ekrs.ms.gov.pl/rdf/pd/search_df?krs={krs}` | none | **Blocked** by Incapsula bot protection — see below |
| Name search (web) | `https://wyszukiwarka-krs.ms.gov.pl/` | none | **Blocked** — JS-rendered, session-based; needs Playwright |

- **Rate limit**: KRS REST tolerates ~60 req/min in practice; adapter caps
  at the same. Biała Lista API is generous and we hit it at most once per
  lookup.
- **robots.txt / ToS**: All three Ministry sources are open data — allowed.

## Test companies (used by integration tests)

| Name | KRS | NIP |
|------|-----|-----|
| PKN Orlen S.A. (now ORLEN S.A.) | `0000028860` | `7740001454` |
| KGHM Polska Miedź S.A. | `0000023302` | `6920000013` |
| CD Projekt S.A. | `0000006865` | `7342867148` |
| Allegro.eu S.A. | `0000635012` | — |

## Capabilities

| Capability | Status |
|-----------|--------|
| `lookup_by_identifier` (KRS, NIP, VAT) | ✅ Live |
| `lookup_by_identifier` (REGON) | 🚫 Not implemented — GUS BIR key needed |
| `search_by_name` | 🚫 Not implemented — no public name-search API |
| `fetch_financials` | 🚫 Returns `[]` — RDF host is bot-protected |

## Known limitations

- **No name search.** The KRS REST surface is keyed by KRS number only.
  The public web search at `wyszukiwarka-krs.ms.gov.pl` runs on a JS
  front-end with an XSRF/session form, so it cannot be hit with httpx.
  Reaching it would need Playwright (tracked under the cross-cutting
  browser-pool work in `CLAUDE.md`). The adapter raises
  `AdapterNotImplementedError` rather than ship a brittle scrape.
- **No structured financials yet.** Polish annual financial statements
  (sprawozdania finansowe) are filed to RDF, the
  Repozytorium Dokumentów Finansowych at `ekrs.ms.gov.pl/rdf/pd/`. That
  host is fronted by Incapsula and serves a JS challenge to any plain
  HTTP client — a true browser is required. Once the project gains a
  Playwright pool, the adapter can list filings + download iXBRL/PDF
  blobs.
- **PESEL / surnames are masked** by the KRS API itself (e.g. Director
  `"nazwiskoICzlon": "N**********"`). This is by design and not an
  adapter issue. The `directors` list will contain partial names from
  KRS — credit decisions should rely on the company-level data, not on
  individual identification.

## Status

🟢 **LIVE** — KRS + Biała Lista lookups by KRS / NIP / VAT work against
production endpoints. Name search and structured filings deferred to the
browser-pool milestone.

**Next steps:** wire Playwright pool → enable name search via
wyszukiwarka-krs and RDF filings download.
