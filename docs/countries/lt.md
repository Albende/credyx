# 🇱🇹 Lithuania — Registrų centras (JAR) + VIES

## Identifiers

- **Įmonės kodas** — Company code, 9 digits (`IdentifierType.COMPANY_NUMBER`,
  primary). Issued by Registrų centras and stable for the life of the
  legal entity.
- **PVM kodas** — VAT number (`IdentifierType.VAT`), `LT` + 9 digits for
  legal entities or `LT` + 12 digits for natural persons / temporary
  registrations.

## Sources

- **Registrų centras (JAR)** — https://www.registrucentras.lt/jar/p/
  - Free public name/kodas search via the JAR portal.
  - Per-company detail and filing-history tabs (`?p=1&Tab=2&kodas=...`)
    are free as HTML.
  - **Full filed annual report PDFs are paid** (per document) — out of
    scope for the MVP per project rules. Only the filing year list is
    surfaced.
- **VIES** — https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  - Free SOAP endpoint, no auth, used to resolve an LT VAT → registered
    name + address.
- **JADIS open dataset** — Registrų centras publishes a full CSV dump of
  Lithuanian legal entities under their open-data programme. Not yet
  ingested; would unlock offline name search if bulk loading becomes
  desirable.

**Auth**: None (anonymous HTTPS).
**Rate limit**: 30 req/min self-imposed; JAR has no published quota but
the site is operated by a single body — be polite.
**robots.txt / ToS**: JAR's terms permit public consultation; bulk
extraction (scraping for resale) is not permitted. We hit individual
record pages on demand only.

## Capabilities

| Endpoint | Status | Notes |
|----------|--------|-------|
| `search_by_name` | ✅ | JAR `?p=1&pavadinimas=...` HTML scrape |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | JAR `?p=1&kodas=...` |
| `lookup_by_identifier(VAT)` | ✅ | VIES SOAP |
| `fetch_financials` | ⚠️ | Year list + source URL only; PDFs are paid |
| `health_check` | ✅ | Probes the JAR search endpoint |

## Test companies (REAL)

| Name | Kodas | VAT |
|------|-------|-----|
| AB "Lietuvos energija" / Ignitis grupė | 301844044 | LT100004278519 |
| AB "Pieno žvaigždės" | 110870469 | LT108705113 |
| AB "Snaigė" | 110057511 | LT100575113 |
| Telia Lietuva, AB | 121215434 | LT100001969712 |

## Status

🟢 **Live**. Real free sources (JAR + VIES). No paid APIs used. Filings
return metadata-only; the structured-data upgrade path is to either pay
JAR per document or onboard the JADIS bulk dataset and parse the filed
PDFs offline.

## Known limitations

- JAR's HTML template is undocumented and may shift; the scraper is
  defensive but a wholesale redesign would require updating selectors.
- VIES is rate-limited and occasionally returns `MS_UNAVAILABLE`; we
  treat that as "lookup not currently possible" rather than fabricating
  a record.
- No directors / shareholders / capital data is parsed today — JAR
  exposes those fields only on the paid extract.
