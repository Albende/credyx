# 🇱🇻 Latvia — UR open data + VIES

## Identifiers

- `COMPANY_NUMBER` → Reģistrācijas numurs, 11 digits (typically starts
  with `40`, `41`, `42`, `50`).
- `VAT` → `LV` + 11 digits.

## Sources

- **Uzņēmumu reģistrs (UR) — Enterprise Register** open data on
  [data.gov.lv](https://data.gov.lv/dati/lv/dataset/uz). Free CSV dump
  of every legal entity (regcode, name, legal form, address,
  registration / termination dates). No per-company JSON API on the
  open-data portal — we stream the CSV and filter in memory.
- **UR public web search** at
  [https://www.ur.gov.lv/lv/uznemumu-meklesana/](https://www.ur.gov.lv/lv/uznemumu-meklesana/) —
  HTML only, used as a fallback source URL on the UI.
- **VIES** SOAP endpoint at
  `https://ec.europa.eu/taxation_customs/vies/services/checkVatService`
  to resolve LV VAT numbers.
- **Lursoft** is paid → **explicitly skipped per project rules**. Annual
  report PDFs are sold through Lursoft so `fetch_financials` returns no
  documents.

## Auth & limits

- No API key required.
- Rate limit: 30 req/min (self-imposed, respects data.gov.lv ToS).
- robots.txt / ToS: data.gov.lv is CC-BY open data; VIES has no auth but
  is occasionally throttled.

## Test companies (real)

- AS "Latvenergo" — Reģ # `40003032949`
- AS "airBaltic Corporation" — Reģ # `40003245752`
- SIA "Maxima Latvija" — Reģ # `40003520643`
- AS "Citadele banka" — Reģ # `40103303559`

## Capabilities

| Capability | Source | Notes |
|------------|--------|-------|
| `search_by_name` | data.gov.lv UR CSV | Substring match, case-insensitive |
| `lookup_by_identifier(COMPANY_NUMBER)` | data.gov.lv UR CSV | Exact 11-digit match |
| `lookup_by_identifier(VAT)` | VIES SOAP | Returns canonical name + address |
| `fetch_financials` | n/a | Empty list — PDFs are paid via Lursoft |

## Status

🟢 **Wired (MVP)**. Search + lookup live against free sources; financials
intentionally empty.

**Recommended next step:** add ESEF XBRL ingestion for listed
issuers (Latvenergo, airBaltic, Citadele) once the shared EU ESEF parser
lands in `packages/risk/xbrl_esef.py`.
