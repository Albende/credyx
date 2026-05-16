# 🇨🇲 Cameroon — BVMAC (partial)

## Identifiers

- `COMPANY_NUMBER` → **RCCM** (Registre du Commerce et du Crédit Mobilier).
  Format varies by court of registration, e.g. `RC/DLA/1968/B/1234`
  (Douala) or `RC/YAO/2010/B/0987` (Yaoundé).
- `VAT` → **NIU** (Numéro d'Identification Unique), 14-char tax number,
  e.g. `M021400012345D`.

## Sources

- **BVMAC** — https://www.bvm-ac.com/
  Regional CEMAC stock exchange (Douala). Lists a handful of Cameroonian
  issuers; annual reports posted as PDFs on each issuer's landing page.
  No structured JSON / REST endpoint, no auth.
- **api.cm** — https://api.cm/
  Aggregator portal advertising several Cameroonian government APIs;
  most endpoints behind ad-hoc registration, none expose RCCM / NIU
  machine-readable lookup at the time of writing.
- **CFCE** (Centre de Formalités de Création d'Entreprises) — issues
  RCCM / NIU but **only via in-person counter** or paid extracts. No
  public free API.

## Test companies (real BVMAC issuers)

| Name | Notes |
|------|-------|
| SAFACAM | Société Africaine Forestière et Agricole du Cameroun |
| SOCAPALM | Société Camerounaise de Palmeraies |
| SEMC | Société des Eaux Minérales du Cameroun |

## Status

🟡 **Partial / blocked** —
- `search_by_name`: ❌ raises `AdapterNotImplementedError` (no free machine-readable RCCM search).
- `lookup_by_identifier`: ❌ same.
- `fetch_financials`: 🟡 returns a single pointer (HTML landing URL) for
  the three BVMAC-listed issuers above; `[]` for everything else.
- `health_check`: ✅ probes `bvm-ac.com` reachability.

## Recommended next step

1. Add a Playwright job that crawls each BVMAC issuer page nightly,
   extracts the latest annual-report PDF URL + period end, and replaces
   the curated pointer with a real `FinancialFiling`.
2. Wire `OpenSanctions` and GLEIF as the fallback for name search until
   an official RCCM endpoint becomes available.
3. Phase 2: investigate OHADA's regional "Registre du Commerce et du
   Crédit Mobilier" digitization project (covers 17 West/Central African
   states including CM) — currently pilot-only.
