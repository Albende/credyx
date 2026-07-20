# Italy — GLEIF + VIES + filings.xbrl.org (ESEF)

## Identifiers

- `VAT` (Partita IVA) — 11 digits, optional `IT` prefix. Last digit is a
  Luhn-style mod-10 check (odd positions summed as-is; even positions
  doubled with the digits of the product summed individually).
- `COMPANY_NUMBER` (Codice Fiscale) — for legal entities this is the same
  11-digit string as the Partita IVA. The 16-character individual Codice
  Fiscale is out of scope.
- `LEI` — Legal Entity Identifier; used to pivot into ESEF filings.
- `REA` (Repertorio Economico Amministrativo) — per-chamber, only via paid
  InfoCamere — not supported.

## Sources

- **GLEIF** (free, no auth): `https://api.gleif.org/api/v1/lei-records`.
  JSON:API. Name search via `filter[entity.legalName]` scoped with
  `filter[entity.legalAddress.country]=IT`; reverse lookup via
  `filter[entity.registeredAs]` (the Registro Imprese number = Partita
  IVA). Returns legal name, address, status, legal form, LEI, and the
  Italian registration number. Registro Imprese authority id is
  `RA000407`.
- **VIES VAT validator** (SOAP, free, no auth):
  `https://ec.europa.eu/taxation_customs/vies/services/checkVatService`.
  Country code `IT`. Returns the officially registered name + address for
  a valid Partita IVA; used as the authoritative name/address in lookup.
- **filings.xbrl.org** (free, no auth): `https://filings.xbrl.org/api/filings`.
  XBRL International index of ESEF annual financial reports (mandatory for
  EU-listed issuers since FY2021). Filter by `entity.identifier` = LEI.
  Returns downloadable iXBRL reports (`report_url`), the full report
  package zip (`package_url`), and machine-readable facts (`json_url`),
  all relative to `https://filings.xbrl.org`.
- **Registro Imprese / InfoCamere** — **paid, not used.** Full registry,
  filings, and ownership data for unlisted firms are behind a per-query
  commercial tariff, which the MVP rules forbid.

## Rate limit

30 requests/minute (VIES is shared EU infrastructure; be polite). GLEIF
and filings.xbrl.org are generous but respect the same ceiling.

## Test companies

- Eni S.p.A. — Partita IVA `00484960588`, LEI `BUCRF72VH5RBN7X3VL35`
- Enel S.p.A. — Partita IVA `00811720580`, LEI `WOCMU6HCI0OJWNPRZS33`
- Intesa Sanpaolo S.p.A. — Partita IVA `00799960158`
- UniCredit S.p.A. — Partita IVA `00348170101`, LEI `549300TRUWO2CD2G5692`

## Status

- ✅ **Name search** via GLEIF — Italian entities holding an LEI, with
  Partita IVA / Codice Fiscale surfaced from `registeredAs`. Firms with no
  LEI are only in the paid Registro Imprese.
- ✅ **VAT lookup** via VIES (authoritative name + address), enriched with
  the GLEIF LEI and legal form.
- ✅ **Financials** — real filed ESEF iXBRL annual reports via
  filings.xbrl.org for listed issuers, keyed by LEI (downloadable
  `document_url`). Unlisted entities have no free filed accounts and
  return `[]`.

**Recommended next step (Phase 2):** Parse the ESEF iXBRL / `json_url`
facts into `structured_data` via `packages/risk/xbrl_esef.py` so listed
issuer financials feed the ratio engine directly instead of being
pointer-only.
