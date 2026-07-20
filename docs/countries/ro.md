# 🇷🇴 Romania — ANAF + ONRC

## Identifier

- Primary: `VAT` / `COMPANY_NUMBER` (Cod Unic de Înregistrare — CUI / CIF).
- Format: 2–10 digits. VAT-registered firms prefix with `RO` (e.g. `RO1590082`).
- The adapter strips the `RO` prefix transparently.

## Sources

### ANAF — balance-sheet feed `/bilant` (LIVE — financials)

- URL: `https://webservicesp.anaf.ro/bilant?an=YYYY&cui=NNN`
- Method: `GET`, query params `an` (fiscal year) + `cui`.
- Auth: none. Cost: free.
- Returns the filed annual accounts as the Romanian statutory indicator set
  (`{"an","cui","deni","caen","den_caen","i":[{indicator,val_indicator,
  val_den_indicator},...]}`) in RON — fixed/current assets, inventories,
  receivables, cash, liabilities, equity, share capital, net turnover, gross
  and net profit, average headcount. Non-financial companies use the general
  chart; banks/insurers use a different chart (indicator codes are NOT stable,
  so the adapter maps by **label text**, not `I`-code, and preserves every raw
  indicator under `structured_data.raw_concepts`).
- A year with no filing returns HTTP 200 with `"i":[]` and empty `deni` — the
  adapter skips those and walks back year-by-year until it collects `years`
  real filings. The most recent complete fiscal year is available (e.g. 2025
  filings are live in mid-2026).

### DemoANAF — name search (LIVE — search)

- URL: `https://demoanaf.ro/api/search?q=<name>`
- Method: `GET`. Auth: none. Rate limit: 300 req/min.
- Free aggregator over the full ~4M-row ONRC register. Returns `cui`, `name`,
  `registrationNumber`, `county`, `locality`, `legalForm`, `statusLabel`.
  Crucially it returns the **CUI**, which feeds straight into the ANAF lookup +
  `/bilant` paths. Used because ANAF/ONRC exposes no first-party name-search
  API to foreign IPs and mfinante.gov.ro is geoblocked outside Romania.
- GLEIF (`api.gleif.org`) is a whitelisted key-free alternative but only
  covers LEI holders and returns the Reg. Com. number, not the CUI, so it
  cannot chain into lookup/financials.

### ANAF — VAT validator (LIVE — lookup)

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
- Status: not needed for financials — ANAF `/bilant` already gives filed
  statutory accounts for every registered company, listed or not.

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
| `search_by_name` | LIVE via DemoANAF ONRC index (returns CUI) |
| `lookup_by_identifier` (VAT / COMPANY_NUMBER) | LIVE via ANAF VAT validator |
| `fetch_financials` | LIVE via ANAF `/bilant` (structured RON accounts) |
| `health_check` | LIVE — pings ANAF with a known CUI |

## Status

🟢 **LIVE — search, lookup, and financials all return real data, no API key.**

**Next steps:** improve the balance-sheet indicator mapping for the bank /
insurer taxonomies (currently only the general chart is fully typed; bank
indicators are preserved raw under `raw_concepts`). Optionally replace the
DemoANAF search dependency with a first-party ONRC feed if one becomes
reachable without geoblocking.
