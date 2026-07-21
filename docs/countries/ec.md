# Ecuador — GLEIF (SUPERCIAS / SRI geo-blocked)

## Identifier

- Type: `VAT` (primary — RUC doubles as the Ecuadorian corporate tax /
  VAT identifier) with `COMPANY_NUMBER` exposed as an alias. `LEI` is also
  accepted for lookup, since the live source is the LEI registry.
- Format: **RUC** (Registro Único de Contribuyentes). **13 digits**,
  layout `PPCCCCCCCCDDD001`:
  - `PP` (digits 1–2): province code (01–24).
  - Digit 3: contributor class. `9` = sociedad / persona jurídica,
    `6` = institución pública, `0–5` = persona natural.
  - Digits 4–10: body identifier.
  - Last three digits: establishment suffix — for the head office this
    is always `001`.
- The adapter accepts every common rendering — `1790010937001`,
  `179.001.0937-001`, `EC 1790010937001` — and validates only on
  length + digit-only content. We deliberately do not enforce a
  province-code range, because several legacy public-sector RUCs predate
  the modern banding.

## Sources

### Live source — GLEIF

Registry data is served from **GLEIF** (Global Legal Entity Identifier
Foundation) — `https://api.gleif.org/api/v1`. Free, no auth, JSON:API.
This is the only free registry-grade source for Ecuadorian companies
reachable from outside Ecuador (see the blocked-source note below).

- **Search by name**:
  `GET /lei-records?filter[entity.legalName]={name}&filter[entity.legalAddress.country]=EC`
  (substring match). Falls back to `filter[fulltext]={name}&filter[entity.legalAddress.country]=EC`
  when the legal-name filter is empty.
- **Lookup by RUC**:
  `GET /lei-records?filter[entity.registeredAs]={ruc}&filter[entity.legalAddress.country]=EC`.
  The Ecuadorian RUC is carried in `entity.registeredAs` for most
  supervised sociedades. A minority of entries (some banks, e.g. Banco
  Pichincha) carry no RUC in GLEIF — look those up by LEI instead.
- **Lookup by LEI**: `GET /lei-records?filter[lei]={lei}`.
- Returns legal name, entity status, legal form (ELF code), registered
  address, incorporation date (`entity.creationDate`), and the LEI.
- GLEIF holds ~137 Ecuadorian entities (mostly larger companies, banks,
  exporters). It is **not** exhaustive coverage of the Ecuadorian
  registry — it is the reachable subset.
- **Rate limit**: generous public API; we self-throttle at 60 req/min.

### Blocked / unreachable sources (documented, not used)

Verified 2026-07 from non-Ecuador egress; retried with curl, httpx,
FlareSolverr, and a real headed Chrome:

- **SUPERCIAS** (Superintendencia de Compañías, Valores y Seguros) —
  current consulta portal at
  `https://appscvsgen.supercias.gob.ec/consultaCompanias/` and
  `https://appscvssoc.supercias.gob.ec/consultaCompanias/`. Every
  `/consultaCompanias/*` request returns an **"Unauthorized Request
  Blocked / Actividad no autorizada"** interstitial (an Ecuador-only
  edge/anti-automation rule; a real headed Chrome from a non-EC IP is
  blocked identically, with no solvable challenge or cookie). The legacy
  mobile host `appscvsmovil.supercias.gob.ec` no longer routes at all.
  SUPERCIAS is the authoritative registry and the home of the free
  "Información Económica" filed-accounts catalog — reachable only from
  inside Ecuador (or via an EC egress proxy, which the MVP does not use).
- **SRI** (Servicio de Rentas Internas) —
  `https://srienlinea.sri.gob.ec/…/obtenerPorNumerosRuc` — TLS handshake
  is dropped from non-EC egress (connect times out).
- **datosabiertos.gob.ec** and **superbancos.gob.ec** — return `403`
  from non-EC egress.
- **Bolsa de Valores de Quito** (`https://www.bolsadequito.com/`) is
  reachable but is a static Joomla CMS: it exposes only a single
  downloadable issuer list and full-text-searchable prospectus PDFs —
  no per-company structured registry or financial feed keyed by RUC.
  **Bolsa de Valores de Guayaquil** returns `404` on its published host.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | Live (GLEIF, country=EC) |
| Lookup by RUC (`VAT` / `COMPANY_NUMBER`) | Live (GLEIF `registeredAs`; RUC-carrying entities) |
| Lookup by LEI | Live (GLEIF) |
| Financials | **Unavailable key-free from non-EC egress** — `fetch_financials` raises `AdapterNotImplementedError`. No free source of filed Ecuadorian financial statements is reachable from outside Ecuador. |

## Test companies (real, GLEIF-verified)

- **OPERADORA Y PROCESADORA DE PRODUCTOS MARINOS OMARSA SA** — RUC
  `0990608504001`, LEI `984500B3EA55BF13F406` — shrimp exporter.
  Works for search **and** RUC lookup.
- **Banco Pichincha C.A.** — LEI `549300CO09CR3FNOZ392` — largest private
  bank. Found by name search; **no RUC in GLEIF**, so look up by LEI.
- **Banco Internacional S.A.** — RUC `1790098354001`,
  LEI `549300XHJYFMEFOFGN31`.
- **Banco Bolivariano C.A.** — RUC `0990379017001`,
  LEI `254900WSPPR3LTYF4B40`.

## Status

Live for name search and RUC/LEI lookup via GLEIF. Financials are not
available from a free, non-EC-reachable source and the adapter raises
rather than fabricate (no-mock rule).

## Phase-2 follow-ups

1. **EC-egress access to SUPERCIAS.** With an Ecuador-based proxy (or when
   run from inside EC), wire the SUPERCIAS consulta portal for exhaustive
   registry coverage and the "Información Económica" filed-accounts catalog
   (free PDF/Excel annual reports) to unblock `fetch_financials`. Route it
   through `fetch_with_bot_bypass` and gate document parsing behind the
   shared PDF pipeline.
2. **SRI validation.** From EC egress, use the SRI consolidated endpoint to
   label RUCs absent from GLEIF (natural-person / public-sector entities).
3. **Securities-exchange filings.** Scrape per-issuer prospectus and
   quarterly filings from BVQ/BVG for the ~30 listed issuers; brittle
   scrape — gate behind the Playwright pool.
4. **Sanctions/PEP.** Wire `OpenSanctionsClient` to screen Ecuadorian
   principals once directors are available (GLEIF does not expose them).
