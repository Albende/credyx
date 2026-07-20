# 🇨🇱 Chile — GLEIF (registry) + SEC EDGAR (financials)

## Identifier

- Type: `VAT` (primary, since the RUT doubles as the corporate tax ID)
  with `COMPANY_NUMBER` accepted as an alias.
- Format: **RUT** (Rol Único Tributario) — 7-9 digits plus a Mod-11
  check character, displayed `XX.XXX.XXX-X`. The check char is a
  decimal digit, or `K` when the remainder is 10.
- Validation: weighted sum with cycling factors 2..7 from the right,
  `mod 11`, then `11 − rem` mapped (11→"0", 10→"K", else digit). The
  adapter normalizes input — strips `CL` prefix, dots, dashes, spaces —
  and rejects bad check digits before any HTTP call.

## Why not the official Chilean registries

Both official sources are unusable for a free, key-free, reachable MVP:

- **SII** (`zeus.sii.cl/cvc_cgi/stc/getstc`) answers direct GETs with
  `alert('Por favor reingrese Captcha'); history.go(-1);` — a hard
  CAPTCHA wall, no free API. Verified live 2026-07.
- **CMF** (`www.cmfchile.cl`, `api.cmfchile.cl`) publishes listed-company
  IFRS filings but **geoblocks non-Chilean egress** — the hosts are
  unreachable (TCP timeout) from outside CL, confirmed live via both
  direct httpx and FlareSolverr. The financial-statement API also
  requires a registered `apikey`.

## Sources (live)

- **GLEIF** — `https://api.gleif.org/api/v1` (free, no key, JSON:API).
  Every Chilean legal entity with an LEI carries its **RUT** in
  `entity.registeredAs`. Powers:
  - `search_by_name` — `filter[entity.legalName]` + `country=CL`.
  - `lookup_by_identifier` — `filter[entity.registeredAs]=<digits>-<dv>`.
  - Coverage is LEI-registered entities only (listed companies, banks,
    insurers, funds, larger corporates) — not the full SII taxpayer base.
- **SEC EDGAR** — `efts.sec.gov` + `data.sec.gov` (free, no key).
  Chilean issuers cross-listed in the US file audited **IFRS** annual
  reports as **Form 20-F**. `fetch_financials` resolves the RUT → legal
  name via GLEIF, finds the filer's CIK in EDGAR's 20-F full-text index
  (picking the CIK appearing in the most matching filings), confirms it
  is a Chilean filer (`stateOrCountry == "F3"`), and returns each 20-F as
  a `FinancialFiling` with a `document_url` that genuinely downloads from
  `www.sec.gov/Archives`. Chilean companies with no US listing have no
  free filing feed and return `[]` — never fabricated data.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🟢 GLEIF name search, constrained to CL |
| Lookup by RUT | 🟢 GLEIF `registeredAs` lookup (LEI-registered entities) |
| Financials | 🟢 SEC 20-F for US-cross-listed CL issuers; `[]` otherwise |

## Rate limit

`rate_limit_per_minute = 30`. GLEIF and SEC EDGAR both tolerate more, but
we stay conservative. SEC requires a descriptive User-Agent (supplied by
the shared HTTP client).

## Test companies

- **Banco de Chile — `97.004.000-5`** — fully working across all three
  methods (GLEIF name + RUT lookup; SEC 20-F as "BANK OF CHILE", ticker
  BCH, CIK 1161125). Use this as the canonical live test.
- Empresas COPEC S.A. — `90.690.000-9` — GLEIF search/lookup work;
  financials `[]` (no US listing).
- Falabella S.A. — `90.749.000-9` — GLEIF search/lookup work; financials
  `[]` (no US listing).
- Banco de Chile ADR peers that also file 20-F: SQM, Enel Chile,
  Enel Américas — financials work; useful cross-checks.

All pass the Mod-11 checksum.

## Status

🟢 **Live**. RUT validation + normalization fully working and tested.
Registry (name search + RUT lookup) served from GLEIF. Financials served
from SEC EDGAR 20-F for US-cross-listed issuers. No API key required.

**Recommended next steps:**

1. When a CL-egress deployment (or CL proxy) is available, add CMF as a
   financials source for the many listed CL companies not cross-listed in
   the US, and parse CMF CL-IFRS XBRL into `structured_data`.
2. Wire a Playwright + captcha-solving path to SII behind the browser
   pool for RUT lookup of non-LEI entities (broadens registry coverage
   beyond GLEIF).
3. One-shot importer for the monthly datos.gob.cl SII dump into Postgres
   so `search_by_name` can also serve non-LEI companies from a local
   mirror.
