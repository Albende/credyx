# Malta — GLEIF + VIES + XBRL Filings Index

## Identifiers

- `COMPANY_NUMBER` — "C" + 1–7 digits (e.g. `C2833`, `C 22334`).
- `VAT` — `MT` + 8 digits.

## Sources

- **GLEIF (Global Legal Entity Identifier Foundation)** —
  https://api.gleif.org/api/v1/lei-records
  - Free JSON API, no key. Golden-copy LEI records carry the Maltese
    registry number in `entity.registeredAs` ("C 2833", with a space),
    the legal name, addresses, `status`, `legalForm` (ELF code) and
    `creationDate`.
  - Used for **name search** (`filter[entity.legalName]` + country `MT`)
    and **company-number lookup** (`filter[entity.registeredAs]`).
  - Coverage: every entity holding an LEI — all listed / regulated
    companies plus a large and growing slice of active SMEs. Companies
    with no LEI are not found (we return `[]` / `None`, never fabricated).
- **VIES** — https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  - Free SOAP endpoint, validates an MT VAT and returns registered name +
    address. VIES proxies each member state's own node; Malta's node is
    intermittently unavailable and then reports the VAT as unconfirmed —
    the adapter returns `None` in that case rather than inventing data.
- **XBRL Filings Index (filings.xbrl.org)** — https://filings.xbrl.org/api/filings
  - Free JSON:API, no key. Public repository of EU listed-company ESEF
    (iXBRL) annual financial reports. Every Malta-domiciled issuer files
    here; each filing exposes a downloadable report package (`package_url`,
    a real `.zip` that HTTP 200s with `Content-Type: application/zip`),
    keyed by LEI. The adapter resolves COMPANY_NUMBER → LEI via GLEIF, then
    lists the issuer's ESEF filings as `ANNUAL_REPORT`s.

### Retired source

- **MBR online system** — the register migrated from `registry.mbr.mt`
  (Struts) to a Wyzer SPA at `register.mbr.mt` / `baros.mbr.mt`. The public
  company-search page (`/app/query/search_for_company`) now redirects to an
  Azure B2C login, so it is no longer scrapeable key-free. MBR launched paid
  "Subject Person" API packages (Company Search / Basic / Full Company
  Details) in March 2026 — a Phase-2 paid integration, out of MVP scope.

## Test companies

| Name | Company Number | LEI |
|------|----------------|-----|
| Bank of Valletta plc | C 2833 | 529900RWC8ZYB066JF16 |
| HSBC Bank Malta plc | C 3177 | |
| GO plc (telecom) | C 22334 | |
| International Hotel Investments plc | C 26136 | |

## Status

Wired, fully key-free. Search + company-number lookup via GLEIF, VAT lookup
via VIES, financials via the ESEF `filings.xbrl.org` index (real downloadable
iXBRL annual reports for LEI-holding issuers). Companies with no LEI return
`[]` for financials and are absent from GLEIF search — their non-ESEF filings
sit behind MBR's per-document paywall.

**Phase-2 upgrade paths:**
- Subscribe to MBR's paid Subject-Person Company Search / Full Company
  Details APIs for full non-listed coverage and structured filing lists.
- Parse the ESEF iXBRL packages (via `packages/risk/xbrl_esef.py`) into
  `structured_data` so the risk engine gets balance-sheet figures directly.
