# 🇱🇺 Luxembourg — LBR / RCSL + VIES

## Identifiers

- `COMPANY_NUMBER` — RCS (Registre de Commerce et des Sociétés) number,
  format `B` + 1–7 digits (e.g. `B82454`). Accepts "B82454", "82454",
  "B 82 454", or "RCS B82454" as input; canonical form is `B82454`.
- `VAT` — `LU` + 8 digits (e.g. `LU24876214`).

## Sources

### LBR (Luxembourg Business Register)

- Public site: <https://www.lbr.lu/>
- Free public search:
  `https://www.lbr.lu/mjrcs/jsp/IndexActionNotSecured.action`
- HTML scrape only — no public JSON or REST API.
- Full filed extracts ("comptes annuels", "statuts", etc.) are sold per
  document (~€2–5). Not wired in MVP per the no-paid-APIs rule.
- robots.txt / ToS: search is intended for human use. We throttle to
  30 req/min and identify the crawler in the `User-Agent`.

### VIES (EU VAT Information Exchange)

- SOAP endpoint:
  `https://ec.europa.eu/taxation_customs/vies/services/checkVatService`
- Returns `valid`, `name`, `address` for a recognised LU VAT.
- Free, no auth, no key. Honor 429 / `Retry-After` like every adapter.

### Open Data Luxembourg

- <https://data.public.lu/> publishes occasional LBR open-data dumps.
- Not used in this adapter — bulk feed isn't a live lookup primitive.
  Worth wiring later for entity-graph enrichment.

## Capabilities

| Method                                  | Source                   | Status |
| --------------------------------------- | ------------------------ | ------ |
| `search_by_name`                        | LBR public search scrape | live   |
| `lookup_by_identifier(VAT)`             | VIES SOAP                | live   |
| `lookup_by_identifier(COMPANY_NUMBER)`  | LBR detail scrape        | live   |
| `fetch_financials`                      | n/a                      | returns `[]` (paid extracts only) |

`fetch_financials` returns an empty list intentionally — filings on LBR
are paywalled per document. Upgrade path: integrate a paid LBR extract
licence or scrape published annual report PDFs from issuer IR pages
(SES, ArcelorMittal, RTL Group, etc.) and feed them through the planned
PDF extraction pipeline.

## Health probe

VIES check against the ArcelorMittal LU VAT (`LU24876214`). Reports
`DEGRADED` if VIES is reachable but returns invalid; `ERROR` if the
SOAP call fails outright.

## Test companies (real)

- ArcelorMittal S.A. — RCS `B82454`, VAT `LU24876214`
- SES S.A. — RCS `B81267`, VAT `LU17996777`
- RTL Group S.A. — RCS `B10807`
- B&S Group S.A. — RCS `B202216`

## Status

🟢 **Live (lookup + search; financials gap documented).**

## Known fragility

- The LBR results template is HTML-only and unversioned. If they redesign
  it, `_parse_lbr_search_results` returns `[]` and the API surfaces an
  empty list rather than fabricated rows. Add fixtures and revisit
  the parser in that case.
- VIES occasionally rate-limits aggressive callers — adapter throttles
  at 30 req/min.
