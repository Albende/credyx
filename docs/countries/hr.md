# 🇭🇷 Croatia — Sudski registar + FINA RGFI

## Identifiers

- **OIB** (Osobni identifikacijski broj) — 11 digits. Acts as both corporate
  tax ID and VAT base. Validated locally via ISO 7064 MOD 11,10.
  Maps to `IdentifierType.VAT` (carrier prefix `HR` when round-tripped).
- **MBS** (Matični broj subjekta) — court registration number, up to 9 digits.
  Maps to `IdentifierType.COMPANY_NUMBER`. Zero-padded to 9 digits.

## Sources

### Registry — Sudski registar (Croatian Court Registry)

- Public portal (HTML): https://sudreg.pravosudje.hr/registar/f?p=150
- **Open data JSON API**: https://sudreg-data.gov.hr/api/javni — free, no key.
  - `/subjekt_naziv?naziv=...` — search by name.
  - `/subjekt_detalji?tip_identifikatora={oib|mbs}&identifikator=...` — lookup.
- **Rate limit**: 30 req/min (self-imposed, no documented hard limit).
- **Auth**: none.
- **ToS / robots.txt**: open government data; respectful crawler UA only.

### Financials — FINA RGFI

- https://rgfi.fina.hr/IzvjestajiRGFI.action — free public annual-report
  listing per OIB. Returns the per-year filing index (PDF). Equivalent to
  Slovak `registeruz.sk`. Currency was HRK ≤ 2022 and EUR from 2023-01-01.

### VIES

- HR VAT lookup via SOAP at the EU VIES service is available for
  cross-border VAT validation; not yet wired here since OIB checksum
  validation + Sudski registar already covers identity confirmation.

## Test companies

- INA d.d. — OIB `27759560625`, MBS `080000604`
- HEP d.d. — OIB `28921978587`, MBS `080007911`
- Pliva Hrvatska d.o.o. — OIB `41538015885`
- Konzum plus d.o.o. — OIB `39963122365`

## Status

✅ **LIVE** — full registry search + lookup via `sudreg-data.gov.hr` OData
and annual-report discovery via FINA RGFI (PDF listing by year).
Structured XBRL parsing of FINA filings is deferred — the current adapter
returns one `FinancialFiling(type=ANNUAL_REPORT, document_format="pdf")`
record per reporting year with `source_url` pointing at the listing page,
so the LLM pipeline can fetch and excerpt the PDFs once the cross-cutting
PDF text-extraction worker is wired in.
