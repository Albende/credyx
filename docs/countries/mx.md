# 🇲🇽 Mexico — GLEIF + SEC EDGAR

## Identifier

- Type: `VAT` (RFC) — also accepted as `COMPANY_NUMBER`; `LEI` accepted too.
- Format: **12 chars** for *personas morales* = 3 letters + 6 digits
  (YYMMDD, incorporation date) + 3 alphanumerics ("homoclave").
- Personas físicas use 13 chars; the adapter rejects them — out of scope for
  B2B credit.
- The 6-digit YYMMDD block is decoded into `incorporation_date` (SAT encodes
  the constitution date in the RFC).

## Sources used

| Source | URL | Free? | Key? | Used for |
|--------|-----|-------|------|----------|
| GLEIF LEI index | https://api.gleif.org/api/v1/lei-records | Yes | No | name search + RFC lookup |
| SEC EDGAR full-text search | https://efts.sec.gov/LATEST/search-index | Yes | No | resolve issuer name → CIK |
| SEC EDGAR submissions | https://data.sec.gov/submissions/CIK{cik}.json | Yes | No | 20-F annual-report filings |

Why these: Mexico has **no** free official corporate-registry API. SAT's RFC
verifier is CAPTCHA-gated, SIGER/RPC filings are paid per-state, and there is
no Receita-style open API (unlike BR CNPJ). GLEIF is the one free, key-less
source that maps a company's official **RFC** (stored in
`entity.registeredAs`, registration authority `RA000449` = SAT) to its legal
name, address, status, and ELF legal-form code. For financials, Mexican
issuers cross-listed in the US file their annual report as **Form 20-F** on
SEC EDGAR — full-text search resolves the GLEIF legal name to a CIK, and the
submissions feed yields the real, downloadable filing documents.

### Sources evaluated and rejected

| Source | URL | Why not |
|--------|-----|---------|
| SAT RFC validator | portalsat.plataforma.sat.gob.mx/ConsultaRFC | CAPTCHA-gated JSF form, no JSON |
| BMV (Bolsa Mexicana) | www.bmv.com.mx | HTML/JS-only, key is ticker not RFC, no clean JSON API |
| SIGER 2.0 / RPC | per-state | Mostly paid |
| SAT Lista 69 / 69-B | sat.gob.mx CSV | Blacklist screening only (Phase-2 risk wiring) |

## Behavior

- `requires_api_key = False`, `rate_limit_per_minute = 30`.
- `search_by_name(name)` → GLEIF `lei-records` filtered by
  `entity.legalName` + `entity.legalAddress.country = MX`. Returns
  `CompanyMatch` with RFC + LEI identifiers, legal address, status.
- `lookup_by_identifier(VAT|COMPANY_NUMBER, rfc)` → GLEIF lookup by
  `entity.registeredAs = rfc`. Returns `CompanyDetails` (name, status,
  ELF legal form, decoded incorporation date, registered address,
  RFC + LEI). `lookup_by_identifier(LEI, lei)` also supported. Returns
  `None` when the entity has no LEI record (no fabrication).
- `fetch_financials(rfc, years)` → GLEIF resolves the RFC to a legal name,
  EDGAR full-text search resolves the name to a CIK, and the submissions
  feed yields Form 20-F annual reports as `FinancialFiling` (year,
  `ANNUAL_REPORT`, period_end, downloadable `document_url`, filing-index
  `source_url`). Returns `[]` for companies not cross-listed in the US.
  No line items are invented — only real filing metadata + document links.
- `health_check` probes GLEIF and reports `OK` (reachable) or `ERROR`.

## Coverage limits

- GLEIF only holds Mexican entities that have obtained an LEI (large /
  regulated firms and their counterparties). SMEs without an LEI resolve to
  `None` / `[]` — not fabricated.
- EDGAR financials exist only for the ~30 Mexican issuers cross-listed in the
  US (América Móvil, Pemex, Cemex, FEMSA, Grupo Televisa, etc.).

## Test companies (RFC verified live in GLEIF)

| Company | RFC | LEI | EDGAR CIK (20-F) |
|---------|-----|-----|------------------|
| Petróleos Mexicanos (Pemex) | PME380607P35 | 549300CAZKPF4HKMPX17 | 0000932782 |
| América Móvil S.A.B. de C.V. | AMO000925Q31 | 5493000FNR3UCEAONM59 | 0001129137 |

(RFCs corrected against GLEIF `registeredAs`; the prior doc's `PEP970814I20`
and `AMX010120CKA` were subsidiary/legacy codes not resolvable via GLEIF.)

## Status

🟢 **Live** — name search + RFC lookup via GLEIF; annual-report financials via
SEC EDGAR 20-F for US-cross-listed issuers. No API key required.

## Recommended next steps

1. Wire SAT Lista 69 / 69-B CSV ingestion as an automatic red-flag screen in
   `packages/risk/engine.py`.
2. Parse the 20-F XBRL/financial statements into `structured_data` line items
   (currently metadata + document link only).
3. Add BMV scraping for non-US-listed BMV issuers (key by ticker, build a
   ticker↔RFC map) to widen financials coverage beyond cross-listed firms.
