# Austria — JustizOnline Firmenbuch / GLEIF·ESEF / VIES

## Identifiers

- **Firmenbuchnummer (FN)** — digits (1–6) + optional check letter, e.g.
  `FN 93363 z`. Mapped to `IdentifierType.COMPANY_NUMBER` and used as the
  **primary identifier**. Canonical form in the adapter is `<digits><letter>`
  lower-case (no spaces, no "FN" prefix), e.g. `93363z`.
- **UID (Austrian VAT)** — `ATU` + 8 digits, e.g. `ATU12832407`. Mapped to
  `IdentifierType.VAT`. Canonical form in the adapter is `U########`
  (no `AT` prefix); VIES wants the country code separately.

## Sources

- **JustizOnline Firmenbuch** (https://justizonline.gv.at/jop/web/firmenbuchabfrage)
  — the Ministry of Justice business-register portal. Its free public search is
  backed by a key-free JSON API:
  - `GET /jop/service/fba/search?term=<name-or-FN>&size=<n>&page=0` → fuzzy
    match, returns `{fnr, name, domicile, status, id}`. Optional `&state=ACTIVE`.
  - `GET /jop/service/fba/{id}` → free basic extract: legal form, registered
    address, status. (`id` is the `search` result id, e.g. `93363z_15`.)
  - The full/historical extract and filed documents behind these are paid
    (~€4.63 / €7.80) and require no login for the basic data used here.
- **GLEIF** (https://api.gleif.org) — Austrian FNs appear in golden-copy records
  as `entity.registeredAs` (plain `<digits><letter>`, e.g. `93363z`), giving a
  free **FN → LEI** bridge for `AT`-domiciled entities.
- **XBRL Filings Index** (https://filings.xbrl.org) — public ESEF repository of
  EU listed-company annual financial reports. Every AT-domiciled issuer files an
  iXBRL report here, keyed by LEI, with a downloadable report package
  (`package_url`, a `.zip`/`.xbri` iXBRL package). Query:
  `GET /api/filings?filter=[{"name":"entity.identifier","op":"eq","val":"<LEI>"}]`.
- **VIES** (https://ec.europa.eu/taxation_customs/vies/) — SOAP, free, no auth.
  Validates AT UIDs. Austria is in the privacy-restricted group (AT/DE/ES/CY):
  VIES does **not** return name/address for AT, only the validity flag.
- **Paid alternatives (out of scope)**: Compass.at, KSV1870, Creditsafe AT,
  Firmenbuch full/historical extracts and the filed `Urkundensammlung`
  (annual accounts) documents at €1–€10/doc.

## Capabilities

| Capability     | State | Reason |
| -------------- | ----- | ------ |
| `search`       | ok    | JustizOnline FBA JSON search (all registered companies). |
| `lookup` (FN)  | ok    | JustizOnline FBA basic extract: name, legal form, address, status. |
| `lookup` (VAT) | ok    | VIES validates UID (name/address redacted for AT). |
| `financials`   | ok (listed issuers) | ESEF annual reports via GLEIF FN→LEI + filings.xbrl.org; empty list for non-LEI / non-listed companies. |

## Test companies

All FNs verified live against the JustizOnline register (the register is
authoritative — some older third-party FN lists are stale):

- OMV Aktiengesellschaft — FN `93363z`, LEI `549300V62YJ9HTLRI486`
  (ESEF filings 2020–2025)
- voestalpine AG — FN `66209t`, LEI `529900ZAXBMQDIWPNB72`
  (ESEF filings, fiscal year end 31 Mar, 2021–2026)
- Erste Group Bank AG — FN `33209m`
- Vienna Insurance Group AG Wiener Versicherung Gruppe — FN `75687f`

VIES may mark any UID as invalid at any time if registration changes; the
adapter never invents a record when VIES returns `valid=false`, and returns an
empty financials list when an issuer has no ESEF filing.

## Status

Fully working (key-free). Health: `ok` when the JustizOnline FBA search
responds, `degraded`/`error` otherwise.

**Notes / next steps:**

1. Financials coverage is limited to LEI-holding / listed issuers — the free
   reality for Austria, since filed SME annual accounts sit behind paid
   Firmenbuch documents. A Phase-2 paid Compass.at / KSV1870 client would add
   SME filings + directors/shareholders.
2. The `_esef` report packages are downloadable iXBRL; wiring them through the
   planned `packages/risk/xbrl_esef.py` parser would turn filing metadata into
   structured balance-sheet data for the risk engine.
