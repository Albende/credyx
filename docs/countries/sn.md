# 🇸🇳 Senegal — APIX + BRVM

## Identifiers

- **RCCM** (Registre du Commerce et du Crédit Mobilier) — West-African
  unified format `SN-{LOC}-YYYY-{TYPE}-{SEQ}` (e.g. `SN-DKR-2003-B-1234`).
  Mapped to `IdentifierType.COMPANY_NUMBER`.
- **NINEA** — 9-digit tax/statistical identifier, optional trailing
  alphanumeric check character. Mapped to `IdentifierType.VAT`.

## Sources researched

| Source | URL | Why not used in MVP |
|--------|-----|---------------------|
| APIX (creationdentreprise.sn) | https://creationdentreprise.sn/ | Public side is a session-bound web form. No JSON/REST API; full RCCM/NINEA records sit behind authenticated workflows. |
| BRVM (regional exchange) | https://www.brvm.org/ | Free annual reports for the 8 UEMOA countries' listed issuers, **PDF only**. Used here for the `fetch_financials` source pointer for listed Senegalese tickers. |
| GLEIF | https://gleif.org | Already wired in `_global` — partial coverage of large Senegalese groups. |
| OpenCorporates (free tier) | https://opencorporates.com | No Senegalese jurisdiction in the free tier as of 2026-05. |

Paid commercial registries (Coface, Dun & Bradstreet, Bureau van Dijk
Orbis) are explicitly excluded by the MVP rules.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | ❌ | Raises `AdapterNotImplementedError`. APIX session-bound, BRVM is ticker-indexed not name-indexed. |
| `lookup_by_identifier` | ❌ | Validates RCCM/NINEA shape, then raises `AdapterNotImplementedError`. No free public lookup API. |
| `fetch_financials` | 🟡 | Returns `[]`. BRVM publishes PDFs; structured extraction belongs in the future PDF pipeline. Known Senegalese BRVM tickers preserved in `_SN_BRVM_TICKERS` for when that pipeline lands. |
| `health_check` | ✅ | Probes https://www.brvm.org/ for reachability. Reports `DEGRADED` because search/lookup are unavailable. |

## Senegalese BRVM-listed issuers (test companies)

- **Sonatel S.A.** — ticker `SNTS` (telco, dominant BRVM-listed Senegalese name).
- **BICIS** (Banque Internationale du Commerce et de l'Industrie du Sénégal) — ticker `BICC`.
- **SODE Sénégal** — ticker `SDSC` (partial coverage).
- **Total Sénégal** — ticker `TTLS` (partial coverage).

## Status

🟡 **Blocked / Partial** — health check + identifier validation only.
Real registry data is unreachable for free during MVP.

**Recommended next steps:**

1. Wire the project-wide PDF text-extraction pipeline (Celery worker
   from `pypdf`), then implement a `_brvm` document fetcher that pulls
   the issuer's annual-report PDFs from https://www.brvm.org/ keyed on
   the ticker map, extracts text, and passes it to the LLM via
   `pdf_text_excerpts`.
2. If/when APIX exposes a developer API (or once a budget exists for a
   paid Coface/CDE feed), promote `search_by_name` and
   `lookup_by_identifier` to live implementations and flip the adapter
   to `OK`.
3. Consider a UEMOA-wide adapter (BJ, BF, CI, GW, ML, NE, SN, TG)
   sharing the BRVM client — most listed-company data is structurally
   identical across the 8 jurisdictions.
