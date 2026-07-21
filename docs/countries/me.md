# 🇲🇪 Montenegro — Tax Administration white list + Montenegroberza (MNSE)

## Identifiers

- **PIB** (Poreski identifikacioni broj) — 8-digit tax identifier. Maps to
  `IdentifierType.VAT` and is the adapter's `primary_identifier`. The
  optional `ME` prefix is stripped on normalization.
- **MB** (Matični broj) — 8-digit company/registration number issued by the
  business register. Maps to `IdentifierType.COMPANY_NUMBER`. MNSE prints
  it without the leading zero (`2289377`); the adapter left-zero-pads it to
  8 digits. Montenegrin companies frequently share the same value for PIB
  and MB, but the registers are distinct so both types are kept.

## Sources

### Registry — Tax Administration "Bijela lista poreskih obveznika"

- Open-data landing: <https://data.gov.me/dataset/bijela-lista-poreskih-obveznika>
- Live download URL is resolved through the CKAN API
  (`/api/3/action/package_show?id=bijela-lista-poreskih-obveznika`) so a
  re-published file is picked up automatically.
- A single XLSX maps `PIB → registered company name` for every white-listed
  (compliant) Montenegrin taxpayer — the ~600 companies that make up the
  credit-relevant B2B universe (banks, insurers, utilities, telecoms, large
  trading and industrial firms). The workbook inflates to 80 MB of empty
  rows, so the adapter reads only `sharedStrings.xml` from the zip and pairs
  each 8-digit PIB with the name that follows it. No external XLSX library
  is used (stdlib `zipfile` only). Parsed once and cached in-process.
- Backbone for `search_by_name` (case/diacritic-insensitive name substring)
  and `lookup_by_identifier` (PIB/MB → name). Companies outside the white
  list return `None`/`[]` — never a fabricated record.
- **Auth**: none. **Format**: XLSX open data. **Currency**: EUR.

### Financials + enrichment — Montenegroberza / Montenegro Stock Exchange (MNSE)

- <https://www.mnse.me/> (the old `montenegroberza.com` domain is now a
  parked link-farm and `mse.co.me` no longer resolves — do not use them).
- **Search API**: `/symbols.asp?term=<name>` returns JSON
  `[{label, id, issuer_desc}]` (symbol, internal stock id, issuer name).
- **Issuer profile**: `/code/navigate.asp?Id=14&stockId=<id>` yields the
  registered address, matični broj, NACE activity code, ISIN, and the
  **filed financial + audit reports as downloadable PDFs**
  (`/upload/documents/issuer/<SYMBOL>/…`). The adapter reads only the
  "Finansijski i revizorski izvještaji" section, so AGM notices and press
  releases are excluded. Each `document_url` is a real per-company file
  (verified `200`/`206`, `application/pdf`).
- **Important**: mnse.me serves a stripped WAP page to non-browser
  user-agents. The adapter sends a desktop browser `User-Agent` to get the
  full desktop site.
- Non-listed companies have no free filings source, so `fetch_financials()`
  returns `[]`.

### Dead / blocked sources (audited 2026-07)

- `crps.mpa.gov.me`, `crps.me`, `www.pretraga.crps.me` — the former CRPS web
  register; domains parked or `410 Gone`.
- `irms.tax.gov.me` (the new IRMS/CRPS portal, live for the 2026 registration
  law) — answers `503 Service Unavailable` to every off-Montenegro request
  (tested via httpx, a headless Chrome / FlareSolverr, and a second cloud
  IP). Effectively geo-fenced; unusable from outside ME. Re-evaluate if a
  Montenegro egress becomes available.
- OpenCorporates open API — now `401` (key required); not used.

## Test companies

- Crnogorski Telekom A.D. Podgorica — PIB/MB `02289377`, MNSE symbol `TECG`
- Elektroprivreda Crne Gore A.D. Nikšić — PIB/MB `02002230`, symbol `EPCG`
- (MNSE-listed but not white-listed, so lookup returns `None`):
  Crnogorska komercijalna banka `02297473`, Plantaže 13. jul `02001306`

## Status

🟢 **LIVE** — `search_by_name`, `lookup_by_identifier`, and
`fetch_financials` all return real data with no API key. Search + lookup are
backed by the Tax Administration white list; financials are real per-issuer
filing PDFs from MNSE. Coverage is bounded to white-listed and MNSE-listed
companies because the official CRPS/IRMS web register is currently
unreachable from outside Montenegro — a documented source outage, not an
adapter limitation. When IRMS becomes reachable (or a ME egress is added),
its per-company profile endpoint can widen `lookup`/`search` to all entities.
