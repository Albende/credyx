# 🇱🇺 Luxembourg — GLEIF + VIES + filings.xbrl.org

## Identifiers

- `COMPANY_NUMBER` — RCS (Registre de Commerce et des Sociétés) number,
  format `B` + 1–7 digits (e.g. `B82454`). Accepts "B82454", "82454",
  "B 82 454", or "RCS B82454" as input; canonical form is `B82454`.
- `LEI` — 20-char ISO 17442 code (e.g. `2EULGUTUI56JI9SAL165`).
- `VAT` — `LU` + 8 digits (e.g. `LU24876214`).

## Why not LBR directly

The Luxembourg Business Register (`lbr.lu`) redesigned onto an IBM Tivoli
Access Manager (`TAMLoginServlet`) portal. The legacy free `mjrcs`
action URLs used by the old adapter now return `404` or bounce through the
login servlet, and there is no free machine-readable search or per-company
JSON. The RCSL open-data extract that once lived on `data.public.lu` was
withdrawn. Full filed extracts remain paid per document. So the adapter
sources the same facts from three free, key-free, authoritative feeds.

## Sources

### GLEIF (Global Legal Entity Identifier Foundation)

- REST API: `https://api.gleif.org/api/v1/lei-records`
- Free, no key, no auth. Every LU record carries the RCS number in
  `entity.registeredAs` and registrar `RA000432` (= Luxembourg RCS), plus
  the entity's LEI, legal address, status, legal form and creation date.
- Name search: `filter[entity.legalName]=<name>` +
  `filter[entity.legalAddress.country]=LU`.
- RCS lookup: `filter[entity.registeredAs]=B82454` +
  `filter[entity.legalAddress.country]=LU` (falls back to the digits-only
  form). LEI lookup: `GET /lei-records/{lei}`.
- Coverage caveat: GLEIF only indexes entities that hold an LEI (all listed
  companies + most mid/large LU entities). Companies with no LEI simply do
  not match — we never fabricate a row.

### VIES REST (EU VAT Information Exchange)

- Endpoint: `https://ec.europa.eu/taxation_customs/vies/rest-api/ms/LU/vat/{8-digits}`
- Returns `isValid`, `name`, `address` for a recognised LU VAT. Free, no
  auth, no key. (VIES's legacy SOAP endpoint was retired; this is the
  current REST surface.)

### filings.xbrl.org (XBRL International ESEF index)

- API: `https://filings.xbrl.org/api/filings?filter=[{"name":"entity.identifier","op":"eq","val":"<LEI>"}]`
- Free, no key. LU listed issuers file their annual financial report as an
  ESEF (iXBRL) package here. Each filing exposes `period_end`, `package_url`
  (the downloadable `.zip` report package) and `report_url` (the human
  iXBRL viewer page).
- `fetch_financials` resolves the RCS → LEI via GLEIF, then returns one
  `FinancialFiling` per ESEF filing with a real, downloadable
  `document_url`. `currency` is left unset (not asserted) because ESEF
  issuers report in their own presentation currency (e.g. ArcelorMittal in
  USD).

## Capabilities

| Method                                  | Source                          | Status |
| --------------------------------------- | ------------------------------- | ------ |
| `search_by_name`                        | GLEIF `lei-records` (LU-scoped) | live   |
| `lookup_by_identifier(COMPANY_NUMBER)`  | GLEIF `registeredAs` = RCS      | live   |
| `lookup_by_identifier(LEI)`             | GLEIF `lei-records/{lei}`       | live   |
| `lookup_by_identifier(VAT)`             | VIES REST                       | live   |
| `fetch_financials`                      | filings.xbrl.org ESEF index     | live (ESEF filers) |

## Health probe

GLEIF RCS lookup for ArcelorMittal (`B82454`). Reports `DEGRADED` if GLEIF
is reachable but the record doesn't resolve; `ERROR` if the call fails.

## Test companies (real)

- ArcelorMittal S.A. — RCS `B82454`, LEI `2EULGUTUI56JI9SAL165`, VAT `LU24876214`
- SES S.A. — RCS `B81267`, LEI `5493008JPA4HYMH1HX51`, VAT `LU17996777`
- RTL Group S.A. — RCS `B10807`
- B&S Group S.A. — RCS `B202216`

## Status

🟢 **Live (search + lookup + financials).**

## Known fragility

- GLEIF coverage is LEI-scoped: a small non-listed LU company without an LEI
  won't be found. That surfaces as an empty result, never a fabricated one.
- `fetch_financials` covers ESEF filers (listed issuers). Non-listed annual
  accounts are still paid documents on LBR and are intentionally not faked.
- filings.xbrl.org package filenames sometimes contain spaces; the adapter
  URL-encodes the path when building `document_url`.
