# Portugal — VIES + GLEIF + ESEF (filings.xbrl.org)

## Identifier

- Type: `VAT` (NIPC) / `COMPANY_NUMBER` (NIPC)
- Format: 9 digits. NIPC also serves as VAT when prefixed with `PT`.
- Checksum: weights `9,8,7,6,5,4,3,2` against the first eight digits;
  sum mod 11; if remainder < 2 the check digit is 0, else `11 - remainder`.

## Sources

| Endpoint | Use | Auth | Cost |
|----------|-----|------|------|
| `GET https://ec.europa.eu/taxation_customs/vies/rest-api/ms/PT/vat/{NIPC}` | VAT/NIPC validation + registered name/address (JSON) | None | Free |
| `GET https://api.gleif.org/api/v1/lei-records?filter[fulltext]={q}&filter[entity.legalAddress.country]=PT` | PT-scoped company name search (LEI holders) | None | Free |
| `GET https://api.gleif.org/api/v1/lei-records?filter[entity.registeredAs]={NIPC}&filter[entity.legalAddress.country]=PT` | NIPC → LEI resolution | None | Free |
| `GET https://filings.xbrl.org/api/entities/{LEI}?include=filings` | Filed ESEF annual reports (inline XBRL) per company | None | Free |

Rate limit: throttled in-adapter to 30 req/min (VIES rejects bursts).

## Test companies

| NIPC | Name | LEI |
|------|------|-----|
| `500697256` | EDP, S.A. (Energias de Portugal) | `529900CLC3WDMGI9VH80` |
| `504499777` | Galp Energia, SGPS, S.A. | `2138003319Y7NM75FG53` |
| `500100144` | Jerónimo Martins, SGPS, S.A. | `259400A8SZP10GB5IB19` |
| `501525882` | Banco Comercial Português, S.A. (Millennium BCP) | `JU1U6S0DG9YLT7N8ZV32` |

## Status

- ✅ **VAT/NIPC lookup** — VIES REST, returns name + registered address,
  enriched with the LEI from GLEIF when the entity holds one.
- ✅ **Name search** — GLEIF full-text, scoped to PT. Returns LEI + NIPC
  (`registeredAs`) + address. Coverage is limited to **LEI-holding**
  entities (listed issuers, funds, regulated and securities-trading
  firms); Portugal has no free authoritative full-registry name search
  (Registo Comercial Online charges per certificate, Portal da Empresa is
  CAPTCHA-gated). `search_by_name` raises `AdapterNotImplementedError`
  only when GLEIF returns no PT match.
- ✅ **Financials** — real filed ESEF annual reports (inline XBRL) served
  by `filings.xbrl.org`, resolved NIPC → LEI → entity filings.
  `document_url` points at the actual `report.xhtml` (verified to
  download; ~40–50 MB per report), `document_format="xbrl"`. Non-listed
  companies (no LEI / no ESEF filing) return an empty list — never a
  fabricated pointer.

**Recommended next step:** parse the ESEF iXBRL (or the sibling
`json_url` fact set filings.xbrl.org exposes) into `structured_data` once
the ESEF parser (`packages/risk/xbrl_esef.py`) lands, so the risk engine
gets balance-sheet figures without a separate download step.
