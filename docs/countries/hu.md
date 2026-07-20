# 🇭🇺 Hungary — e-beszamolo + VIES

## Identifiers

- `COMPANY_NUMBER` — Cégjegyzékszám, format `NN-NN-NNNNNN` (2-2-6 digits).
  First pair is the court code, second pair the legal form, then a
  6-digit sequential. **Primary identifier.**
- `VAT` — Hungarian VAT: `HU` + 8-digit törzsszám. The 8-digit törzsszám is
  the first 8 digits of the 11-digit Adószám.

## Sources

### e-beszamolo (used — primary)
- URL: https://e-beszamolo.im.gov.hu/
- Ministry of Justice electronic annual-report portal. Every Hungarian
  company files its balance sheets and annual reports here **for free**,
  downloadable as PDF / ESEF ZIP / XML.
- The search form is guarded by an **ALTCHA proof-of-work** challenge (a
  solvable SHA-256 PoW — *not* a human CAPTCHA) plus a one-shot
  "accept terms of use" session flag. Both are satisfied key-free:
  1. `GET  /oldal/beszamolo_kereses` — establish session cookie
  2. `POST /Search/AcceptTermsOfUse` — set terms-accepted flag
  3. `GET  /altcha/api/v1/challenge` — fetch PoW challenge
  4. solve PoW, `POST /Search/Results` (`firmNumber` / `firmName` /
     `firmTaxNumber` + `altcha` payload) — run search
  5. `POST /oldal/kereses_merleglista` (`f=<company-code>`) — list filings
- Drives **name search**, **Cégjegyzékszám lookup**, and **filed annual
  reports** (period, publication date, per-document download filenames + URLs).
- Per-document viewer URLs (`/oldal/kereses_megjelenites?b=..&o=..`) are valid
  only inside the *same* search session that produced them (terms + ALTCHA);
  they open the file in the portal's viewer and are not plain-GET downloadable,
  so they are surfaced in `FinancialFiling.structured_data.attachments` (with
  real filenames/sizes) rather than as a standalone `document_url`.

### VIES (used — VAT lookup)
- URL: `https://ec.europa.eu/taxation_customs/vies/rest-api/ms/HU/vat/{vat}`
- Free public REST. Returns name + address for VAT-registered Hungarian
  companies. No auth. Note: banks / VAT-exempt entities (e.g. OTP Bank) and
  some group-VAT registrations are **not** present in VIES — use a
  VAT-registered company (e.g. Richter Gedeon) to exercise this path.

### Out of scope (paid)
- `e-cegjegyzek.hu` full registry extracts behind paid Hungarian eID.
- `opten.hu`, `ceginfo.hu`, `companyapi.hu` — paid commercial APIs.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | works | e-beszamolo `Search/Results` (ALTCHA solved key-free). Min 4 chars. |
| `lookup_by_identifier(COMPANY_NUMBER)` | works | e-beszamolo search by Cégjegyzékszám → registered name. |
| `lookup_by_identifier(VAT)` | works | VIES; returns name + address (VAT-registered entities only). |
| `fetch_financials` | works | e-beszamolo filing list: year, period-end, publication date, report kind, and per-document download filenames/URLs. |

## Rate limits

- **e-beszamolo enforces a per-IP request cap** ("Túl sok kérés érkezett
  rövid időn belül az IP címről" — too many requests, wait a few minutes).
  Adapter throttles to 20 req/min; each search + filing-list is one session.
  Space calls out; a burst of searches trips a multi-minute soft-block.
- VIES has no documented per-IP limit but soft-blocks abusive callers.
- `Retry-After` is honored by the shared HTTP retry helper.

## Test companies (real)

- **OTP Bank Nyrt.** — Cégjegyzékszám `01-10-041585` (e-beszamolo: name
  search + lookup + financials). Bank → *not* in VIES.
- **Richter Gedeon Nyrt.** — VAT `HU10484878` (VIES lookup returns name +
  Budapest address), Cégjegyzékszám `01-10-040944`.
- MOL Nyrt. — Cégjegyzékszám `01-10-041683` (group VAT, not resolvable via
  plain VIES lookup).
- Magyar Telekom Nyrt. — Cégjegyzékszám `01-10-041928`.

## Status

🟢 **OK** — name search, Cégjegyzékszám lookup and filed annual reports all
live via e-beszamolo (ALTCHA proof-of-work solved without any API key);
VAT lookup live via VIES. No mock data. Financial filings return real
per-company metadata (fiscal period, publication date, document filenames)
and the session-scoped download URLs; document bytes are not persisted.
