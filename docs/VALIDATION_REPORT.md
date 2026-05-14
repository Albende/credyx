# CreditLens — Validation Report

Run: `python scripts/validate.py`

| Country | Search | Lookup | Financials | Risk | Notes |
|---------|:------:|:------:|:----------:|:----:|-------|
| GB (BP) | error: AdapterError | error: AdapterError | error: AdapterError | skip (no KIE_AI_API_KEY) | Missing env var UK_COMPANIES_HOUSE_API_KEY |
| DE (BMW) | not_implemented | not_implemented | not_implemented | skip (no KIE_AI_API_KEY) | Handelsregister.de bulk data is paywalled; OffeneRegister scrape WIP. See docs/countries/de.md. |
| FR (TotalEnergies) | pass | pass | empty | skip (no KIE_AI_API_KEY) |  |
| PL (Orlen) | not_implemented | not_implemented | not_implemented | skip (no KIE_AI_API_KEY) | KRS API requires SOAP cert; CEIDG public for sole-traders. See docs/countries/pl.md. |
| NL (ASML) | error: AdapterError | error: AdapterError | empty | skip (no KIE_AI_API_KEY) | Missing env var NL_KVK_API_KEY |
| ES (Inditex) | not_implemented | not_implemented | not_implemented | skip (no KIE_AI_API_KEY) | BORME publishes daily PDFs; no free structured API. See docs/countries/es.md. |
| IT (Eni) | not_implemented | not_implemented | not_implemented | skip (no KIE_AI_API_KEY) | Registro Imprese requires paid InfoCamere subscription. See docs/countries/it.md. |
| SE (Volvo) | not_implemented | not_implemented | not_implemented | skip (no KIE_AI_API_KEY) | Bolagsverket API is paid (Näringslivsregistret). See docs/countries/se.md. |
| TR (Turk Hava Yollari) | not_implemented | not_implemented | not_implemented | skip (no KIE_AI_API_KEY) | Ticaret Sicil + GİB require Turkish eID; MERSIS public partial. See docs/countries/tr.md. |
| US (Apple) | pass | pass | pass (5) | skip (no KIE_AI_API_KEY) |  |
| CZ (ČEZ) | pass | pass | empty | skip (no KIE_AI_API_KEY) |  |
| NO (Equinor) | pass | pass | empty | skip (no KIE_AI_API_KEY) |  |
| FI (Nokia) | pass | pass | empty | skip (no KIE_AI_API_KEY) |  |

## Summary

- Steps run: **52**
- ✅ pass: **11**
- 🟡 partial / empty / not_found: **5**
- ⚪ not_implemented: **18**
- ⚪ skipped: **13**
- 🔴 errors: **5**