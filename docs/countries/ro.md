# 🇷🇴 Romania — ANAF + ONRC

## Identifier

- Primary: `VAT` / `COMPANY_NUMBER` (Cod Unic de Înregistrare — CUI / CIF).
- Format: 2–10 digits. VAT-registered firms prefix with `RO` (e.g. `RO1590082`).
- The adapter strips the `RO` prefix transparently.

## Sources

### ANAF — VAT validator (LIVE)

- URL: `https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva`
  (v9, July 2026 — the old `PlatitorTvaRest/api/v8/ws/tva` path family 404s;
  the path segments swapped to `api/PlatitorTvaRest/{version}/tva`).
- Method: `POST`, JSON body `[{"cui": <int>, "data": "YYYY-MM-DD"}]`.
- Auth: none.
- Rate limit: generous (documented at ~1 req/sec sustained, batched up to
  100 CUIs per call in v9).
- Returns: `{"found": [...], "notFound": [...]}` — v9 dropped the old
  `cod`/`message` envelope, and answers HTTP 404 (with the same JSON body)
  when no queried CUI is registered. Records still carry legal name, registered
  address, ONRC registration number, fiscal status (active / inactive),
  VAT registration flags, NACE code, phone, incorporation date.
- robots.txt / ToS: public free service, attribution requested.

### ONRC (RECOM)

- URL: https://www.onrc.ro/
- Auth: requires paid commercial contract for structured data.
- Status: not integrated — paid only.

### BVB (Bucharest Stock Exchange)

- URL: https://www.bvb.ro/
- Listed-company annual reports as per-issuer PDF/HTML.
- Status: not integrated — requires a scraper + PDF pipeline.

## Test companies

| Company | CUI |
|---|---|
| OMV Petrom S.A. | 1590082 |
| Banca Transilvania S.A. | 5022670 |
| Dacia Renault Group Romania | 1607819 |
| Hidroelectrica S.A. | 13267213 |

## Capabilities

| Capability | Status |
|---|---|
| `search_by_name` | Not supported (no free name search) |
| `lookup_by_identifier` (VAT / COMPANY_NUMBER) | LIVE via ANAF |
| `fetch_financials` | Not supported (BVB scrape required) |
| `health_check` | LIVE — pings ANAF with a known CUI |

## Status

🟢 **LIVE for CUI / VAT lookup via ANAF.**

**Next steps:** wire a Playwright-based BVB scraper for listed-company
annual reports, and evaluate termene.ro / risco.ro paid feeds for full
financials (Phase 2).
