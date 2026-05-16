# 🇲🇽 Mexico — SAT / BMV / SIGER

## Identifier

- Type: `VAT` (RFC) — also accepted as `COMPANY_NUMBER`.
- Format: **12 chars** for *personas morales* = 3 letters + 6 digits
  (YYMMDD, incorporation date) + 3 alphanumerics ("homoclave").
- Personas físicas use 13 chars; the adapter rejects them — out of scope for
  B2B credit.

## Sources evaluated

| Source | URL | Free? | Usable programmatically? |
|--------|-----|-------|--------------------------|
| SAT RFC validator | https://portalsat.plataforma.sat.gob.mx/ConsultaRFC/ | Yes | ❌ — CAPTCHA-gated JSF form, no JSON endpoint |
| SAT Lista 69 / 69-B | https://www.sat.gob.mx/ — CSV downloads | Yes | ✅ for blacklist screening (not yet wired) |
| BMV (Bolsa Mexicana de Valores) | https://www.bmv.com.mx/ | Yes | ⚠️ — listed issuers only, key is ticker not RFC |
| SIGER 2.0 / RPC (per-state) | various | Mostly paid | ❌ for MVP |
| RUG (movable-asset guarantees) | https://rug.gob.mx/ | Yes | Not relevant to credit profile alone |
| Receita-style open API | — | — | None exists for MX (unlike BR CNPJ) |

## Behavior

- `requires_api_key = False`
- `rate_limit_per_minute = 30`
- `search_by_name` → `AdapterNotImplementedError`. SAT has no public free-text
  search. Route layer falls back to OpenCorporates / GLEIF.
- `lookup_by_identifier(VAT|COMPANY_NUMBER, rfc)` → validates the RFC
  structure, then raises `BlockedByRegistryError` because the SAT verifier is
  CAPTCHA-protected. We refuse to fabricate data (non-negotiable rule #1).
- `fetch_financials(rfc)` → validates the RFC, returns `[]`. BMV requires a
  ticker, not an RFC; without a free RFC→ticker mapping we cannot auto-resolve.
- `health_check` probes the SAT root and reports `DEGRADED` (reachable but no
  usable API) or `ERROR` (unreachable).

## Test companies (real RFCs)

| Company | RFC |
|---------|-----|
| Petróleos Mexicanos (Pemex) | PEP970814I20 |
| América Móvil S.A.B. de C.V. | AMX010120CKA |
| Grupo Bimbo S.A.B. de C.V. | BIM660325IT8 |
| Walmart de México S.A.B. de C.V. | WME9709244W4 |

## Status

🟠 **Blocked** — RFC validator works for humans but is CAPTCHA-gated for
machines. No free corporate registry equivalent to BR CNPJ or US EDGAR exists
in Mexico today.

## Recommended next steps

1. **Phase-2:** integrate OpenCorporates' MX scraper (CC-BY data on
   ~5M Mexican companies) for name search and basic profile.
2. **Phase-2:** wire SAT Lista 69 / 69-B CSV ingestion as an automatic
   red-flag screen in `packages/risk/engine.py`.
3. **Phase-2:** scrape BMV annual-report listings for the ~150 listed
   issuers and key by ticker, then build a ticker↔RFC mapping table.
4. **Phase-3 (paid):** SIGER 2.0 federal portal once per-state APIs unify,
   or a commercial provider (Buró de Crédito, Círculo de Crédito).
