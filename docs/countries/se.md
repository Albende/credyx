# 🇸🇪 Sweden — Bolagsverket open data + GLEIF/ESEF filings

## Identifier

- Primary: `COMPANY_NUMBER` — Organisationsnummer, 10 digits, printed `XXXXXX-XXXX`.
- Also: `VAT` — `SE` + 12 digits, where the first 10 digits are the Org Nr
  and the last two are always `01`.
- The 10th Org Nr digit is a Luhn (mod-10) check digit over the first 9.

## Sources

- **Bolagsverket open data via mackan.eu proxy**
  (https://mackan.eu/tools/bolagsverket/) — a free, key-free, CC-BY-4.0
  JSON proxy over Bolagsverket's official *valuable datasets* (värdefulla
  datamängder) API. Data is Bolagsverket's / SCB's own base register, not
  a scrape of a ToS-restricted aggregator.
  - `GET /search_name.php?q=` — full-text name search over ~1.2M
    registered companies → `search_by_name`.
  - `GET /get_data.php?orgnr=` — authoritative base record (name, legal
    form, status, registered address, SNI codes, registration date,
    business description) → `lookup_by_identifier`.
- **GLEIF** (https://api.gleif.org/api/v1/lei-records) — maps an
  Organisationsnummer to the company's LEI, key-free. Note GLEIF stores
  `registeredAs` inconsistently (hyphenated for some records, plain for
  others), so the adapter tries both forms.
- **filings.xbrl.org** (https://filings.xbrl.org, XBRL International) —
  free, key-free public repository of every EU-listed company's ESEF /
  iXBRL annual financial report. Queried by LEI → real per-company,
  downloadable iXBRL report packages → `fetch_financials`.
- **VIES** (https://ec.europa.eu/taxation_customs/vies/services/checkVatService)
  — kept only as a VAT-validation fallback for `lookup_by_identifier`
  when the Bolagsverket proxy is unreachable.
- **Bolagsverket official gateway** (https://api.bolagsverket.se/) — the
  *valuable datasets* and annual-report APIs are free of charge but the
  gateway is fronted by **mutual-TLS** (client certificate issued on
  registration), so it is not usable key-free and is not used directly.
- **`allabolag.se` / `merinfo.se`** — deliberately *not* used; their ToS
  forbids automated scraping.

**Auth**: None (all three live sources are key-free).
**Rate limit**: 30 req/min adapter-side. mackan.eu asks for "reasonable
use"; GLEIF and filings.xbrl.org are unmetered public APIs.
**robots.txt / ToS**: mackan.eu publishes the proxy for programmatic use
(documented `openapi.json`); GLEIF and filings.xbrl.org are open data.

## Capabilities

| Operation | Status | Notes |
|-----------|--------|-------|
| `search_by_name` | ✅ | Bolagsverket full-text search (mackan proxy). |
| `lookup_by_identifier` (COMPANY_NUMBER) | ✅ | Authoritative base record from Bolagsverket open data. |
| `lookup_by_identifier` (VAT) | ✅ | VAT → Org Nr, then same lookup (VIES fallback). |
| `fetch_financials` | ✅ | Real ESEF iXBRL annual reports for listed issuers via GLEIF + filings.xbrl.org; `[]` for entities with no ESEF filing. |
| `health_check` | ✅ | Bolagsverket proxy probe against Volvo. |

## Test companies

| Company | Org Nr | VAT | ESEF financials |
|---------|--------|-----|-----------------|
| AB Volvo | 556012-5790 | SE556012579001 | ✅ 2021–2024 |
| Telefonaktiebolaget LM Ericsson | 556016-0680 | SE556016068001 | ✅ 2021–2024 |
| H&M Hennes & Mauritz AB | 556042-7220 | SE556042722001 | ✅ 2022–2024 (Nov-30 FY) |
| Spotify AB | 559026-0892 | — | ❌ (parent lists on NYSE, files 20-F not ESEF) |

## Status

🟢 **Fully wired** — search + lookup from Bolagsverket free open data
(mackan.eu proxy over the official *valuable datasets* API), financials
from real ESEF iXBRL annual reports (GLEIF → filings.xbrl.org). All three
operations return real, live, key-free data. Paid Bolagsverket contract
tiers and ToS-grey aggregators (allabolag, merinfo) intentionally skipped
per project rule #2.

**Notes / next steps:**
- `fetch_financials` currently returns filing metadata + a downloadable
  iXBRL package URL. Wire the ESEF XBRL parser (`packages/risk/xbrl_esef.py`
  per CLAUDE.md) to extract structured facts from the package for the
  deterministic ratio engine.
- The mackan.eu proxy is a third-party dependency in front of official
  Bolagsverket data. If it becomes unavailable, the direct replacement is
  the official `api.bolagsverket.se` valuable-datasets API — free of
  charge but requiring a registered mutual-TLS client certificate (a
  shared-infra change: certificate handling in `_base/http.py`).
