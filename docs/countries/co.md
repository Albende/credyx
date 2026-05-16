# 🇨🇴 Colombia — RUES (CONFECAMARAS) + SuperFinanciera

## Identifier

- Type: `VAT` (primary, since NIT is the DIAN-issued tax + corporate ID)
  with `COMPANY_NUMBER` exposed as an alias.
- Format: **NIT** (Número de Identificación Tributaria). 9 or 10 body
  digits plus one check digit, conventionally displayed as
  `XXX.XXX.XXX-D` (e.g. `899.999.068-1`).
- Check digit: weighted sum mod 11. Weights, applied right-to-left over
  the body only, are `[3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59,
  67, 71]`. If the remainder is 0 or 1 the check is the remainder
  itself; otherwise it is `11 - remainder`.
- The adapter accepts every common rendering: `899.999.068-1`,
  `899999068-1`, `CO 899999068-1`, the bare 9-digit body, or the
  11-digit body+check concatenation. A 10-digit input without a dash
  is treated as a 10-digit body (the dash form is the only unambiguous
  way to attach a check digit to a 9-digit body).

## Sources

- **RUES (Registro Único Empresarial y Social)** — `https://www.rues.org.co/`
  - Operated by **CONFECAMARAS** (Confederación Colombiana de Cámaras
    de Comercio), the umbrella body for the country's 57 chambers of
    commerce.
  - **Auth**: none. **Cost**: free.
  - **Endpoints used**:
    - `GET /RM/Consultas?nit={nit_body}` — direct NIT lookup.
    - `GET /RM/Consultas?razon={name}` — name search.
  - Both endpoints back the public Consultas web form; the JSON shape
    is unstable enough that the adapter accepts several common
    response envelopes (`registros`, `data`, `results`, top-level
    array) and falls back to a defensive HTML parse when the portal
    returns its SPA shell rather than JSON. If neither parse
    succeeds, `AdapterNotImplementedError` is raised — never invent.
  - **Rate limit**: undocumented; we self-throttle at 30 req/min.
- **SuperFinanciera de Colombia (SFC)** —
  `https://www.superfinanciera.gov.co/`
  - Publishes annual reports (XBRL / PDF) for SFC-supervised entities
    only: banks, insurers, listed issuers, fiduciaries, broker-dealers.
  - There is **no public per-NIT REST endpoint** to check
    supervision; the buscador de entidades vigiladas is a JavaScript
    SPA. Until a signed dataset is wired up, the adapter conservatively
    returns `[]` from `fetch_financials` rather than fabricate
    supervision status.

## Capabilities

| Capability | Status |
|------------|--------|
| Search by name | 🟢 Live (RUES Consultas) |
| Lookup by NIT (`VAT` / `COMPANY_NUMBER`) | 🟢 Live (RUES Consultas) |
| Financials | 🟡 Limited — `[]` for unsupervised NITs; SFC index URL for supervised entities (no SFC directory wired yet, so currently always `[]`) |

## Test companies (real)

- **Ecopetrol S.A.** — NIT `899.999.068-1` — state-owned oil & gas.
- **Bancolombia S.A.** — NIT `890.903.938-8` — largest Colombian bank.
- **Grupo Argos S.A.** — NIT `890.900.266-3` — infrastructure
  conglomerate.
- **Avianca Group International Limited (Avianca Holdings)** — NIT
  `890.100.577-6` — flag carrier.

All four NIT check digits are verified by the adapter's
`_nit_check_digit` function (see unit tests in
`packages/adapters/co/tests/test_co.py`).

## Status

🟢 **Live** for RUES lookup + name search. 🟡 Financials limited:
SFC-supervised entities need a directory feed before per-year filings
can be surfaced; closed-capital companies have no public balance sheet
source.

## Phase-2 follow-ups

1. **SFC supervised-entity directory**: ingest the
   "Entidades vigiladas" downloadable CSV (Excel today, occasionally
   refreshed) to populate `_is_sfc_supervised`. Once known, each
   supervised entity has annual reports under
   `superfinanciera.gov.co/.../entidades-vigiladas/{slug}` — those
   become structured `FinancialFiling` rows.
2. **CIIU enrichment**: RUES exposes 1–4 CIIU codes per company
   (Colombia's adaptation of NACE Rev. 2). The adapter already
   surfaces them as `nace_codes`; cross-reference DANE's CIIU
   dictionary for human-readable labels in the future industry
   benchmarks table.
3. **DIAN VAT validation**: the Servicios en línea DIAN portal exposes
   a "Consulta inscripción RUT" page but it is JavaScript-rendered
   and behind a CAPTCHA. Out of scope until the Playwright pool
   (`packages/adapters/_base/browser.py`) lands.
4. **Sanctions/PEP**: wire `OpenSanctionsClient` to screen every
   Colombian principal returned by RUES. CO is on the OFAC SDN list
   for narcotics-related designations — this is high-signal for
   credit decisions.
