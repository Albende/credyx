# 🇱🇹 Lithuania — Registrų centras (JAR) + VIES

## Identifiers

- **Įmonės kodas** — Company code, 9 digits (`IdentifierType.COMPANY_NUMBER`,
  primary). Issued by Registrų centras and stable for the life of the
  legal entity.
- **PVM kodas** — VAT number (`IdentifierType.VAT`), `LT` + 9 digits for
  legal entities or `LT` + 12 digits for natural persons / temporary
  registrations.

## Sources

- **JAR open data — Spinta API on data.gov.lt** (key-free JSON) —
  `https://get.data.gov.lt/datasets/gov/rc/jar/`
  - `iregistruoti/JuridinisAsmuo?ja_kodas=<9 digits>` → fast exact-match
    company lookup (name, legal form, status, registration/deregistration
    dates). This backs `lookup_by_identifier(COMPANY_NUMBER)`.
  - `formos_statusai/Forma` and `.../Statusas` are small classifier tables
    resolving the `forma`/`statusas` refs to human labels (cached).
  - Only exact-match on the indexed `ja_kodas` is fast. `ja_pavadinimas`
    (name) and the financial-statement datasets are **not** query-indexed,
    so filtering them per company times out — the JAR portal is used
    instead. Text fields are double-UTF-8-encoded; the adapter round-trips
    latin-1→utf-8 to recover Lithuanian diacritics.
  - `balanso_ataskaitos` / `pelno_ataskaitos` hold **structured** balance
    and P&L line items (real numbers), but are keyed by an unindexed
    `juridinis_asmuo` FK, so per-company retrieval is not feasible on the
    request hot path today. Future upgrade: bulk-ingest these offline.
- **Registrų centras JAR portal** — `https://www.registrucentras.lt/jar/p/`
  (behind Cloudflare → fetched via `fetch_with_bot_bypass`/FlareSolverr)
  - `index.php?pav=<name>&p=1` → free public name search. Backs
    `search_by_name` (parses the `data-label` results table: code, name,
    address, legal form + status).
  - `dok.php?kod=<9 digits>` → the per-company document list. Rows
    "Finansinės atskaitomybės dokumentai / YYYY m. …" enumerate the filed
    annual financial-statement sets. Backs `fetch_financials` (filing
    years, metadata only).
  - **Full filed annual report PDFs are paid** (per document) — out of
    scope for the MVP. No `document_url` is emitted; only filing years.
- **VIES** — https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  - Free SOAP endpoint, no auth, used to resolve an LT VAT → registered
    name + address. Backs `lookup_by_identifier(VAT)`.

**Auth**: None (anonymous HTTPS, no API key).
**Rate limit**: 30 req/min self-imposed. The data.gov.lt Spinta server is a
shared public endpoint that intermittently drops connections / returns empty
bodies under load — `_spinta_get` retries a few times before giving up.
**robots.txt / ToS**: JAR's terms permit public consultation; bulk
extraction (scraping for resale) is not permitted. We hit individual
record pages on demand only. JAR open data is published under the
government open-data programme for reuse.

## Capabilities

| Endpoint | Status | Notes |
|----------|--------|-------|
| `search_by_name` | ✅ | JAR portal `index.php?pav=...` (FlareSolverr) |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | JAR open-data `iregistruoti?ja_kodas=...`; JAR portal `?kod=` fallback |
| `lookup_by_identifier(VAT)` | ✅ | VIES SOAP |
| `fetch_financials` | ⚠️ | Filing years + source URL only; PDFs are paid |
| `health_check` | ✅ | Probes the JAR open-data lookup |

## Test companies (REAL)

| Name | Kodas | VAT |
|------|-------|-----|
| AB "Lietuvos energija" / Ignitis grupė | 301844044 | LT100004278519 |
| Akcinė bendrovė "Pieno žvaigždės" | 124665536 | LT108705113 |
| AB "Snaigė" | 110057511 | LT100575113 |
| Telia Lietuva, AB | 121215434 | LT100001969712 |

Verified live 2026-07 (JAR portal + open data): `search_by_name("Telia")`
returns Telia Lietuva, AB (121215434) among real matches; the code lookup
returns name/legal form (Akcinė bendrovė)/status (active)/reg date
1992-02-06; `fetch_financials(121215434)` lists filed annual FA sets for
2023-2025. Pieno žvaigždės AB is code **124665536** (active) — the older
110870469 no longer resolves as the active AB.

## Status

🟢 **Live**. Real free, key-free sources: JAR open data (data.gov.lt Spinta
API) for code lookup, JAR public portal (via FlareSolverr) for name search
and the per-company filing list, VIES for VAT. No paid APIs used. Filings
return metadata (years) only. Structured-data upgrade path: bulk-ingest the
`balanso_ataskaitos` / `pelno_ataskaitos` open datasets offline (they hold
real line-item numbers but are keyed by an unindexed FK, so per-company
live filtering times out), or pay JAR per document.

## Known limitations

- The JAR portal sits behind Cloudflare; name search and the filing list
  depend on FlareSolverr being reachable. The HTML template is
  undocumented and may shift; parsing is anchored on `data-label` cells.
- The data.gov.lt Spinta server intermittently returns empty bodies /
  drops connections under load; `_spinta_get` retries, and the code lookup
  falls back to the JAR portal when the open-data endpoint is unavailable.
- Only exact `ja_kodas` is query-indexed on the open-data API — name and
  financial-statement datasets are not, so those go through the portal.
- VIES is rate-limited and occasionally returns `MS_UNAVAILABLE`; we treat
  that as "lookup not currently possible" rather than fabricating a record.
- No directors / shareholders / capital data is parsed today — JAR exposes
  those only on the paid extract.
