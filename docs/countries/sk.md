# 🇸🇰 Slovakia — ORSR + RÚZ

## Identifiers

- `COMPANY_NUMBER` — **IČO**, 8 digits (zero-padded). Primary.
- `VAT` — **IČ DPH / DIČ**, `SK` + 10 digits. The 10-digit `DIČ` is the
  underlying tax number; `IČ DPH` is the VAT-registered form.

## Sources

| Use | Source | Auth | Format |
|-----|--------|------|--------|
| Name search | ORSR — https://www.orsr.sk/hladaj_subjekt.asp | none | HTML (windows-1250) |
| Lookup by IČO / DIČ | RÚZ — https://www.registeruz.sk/cruz-public/api/uctovne-jednotky | none | JSON |
| Entity details | RÚZ — `/api/uctovna-jednotka?id={id}` | none | JSON |
| Annual filings list | RÚZ entity `idUctovnychZavierok` | none | JSON |
| Single filing | RÚZ — `/api/uctovna-zavierka?id={id}` | none | JSON |
| Filing PDF | RÚZ — `/domain/financialreport/pdf/{id}` | none | PDF |
| Canonical extract | ORSR — `/vypis.asp?ID={...}&SID={...}&P=0` | none | HTML |

The RÚZ JSON API (`X-API-Version: 2.5`) returns IČO, DIČ, registered name,
legal-form code (`pravnaForma`), incorporation date (`datumZalozenia`),
NACE (`skNace`), address (`ulica` / `psc` / `mesto`), and the list of
every filed annual financial statement and annual report. Currency for
Slovak filings is always EUR (Slovakia adopted the euro in 2009).

**FinStat** (https://finstat.sk/) is paid — explicitly out of scope per
project rules (no paid APIs in MVP).

**RPVS** (https://rpvs.gov.sk/) — Register of Public-Sector Partners,
open bulk dumps. Not currently used; could be a future enrichment for
beneficial-ownership signals on public-procurement counterparties.

## Rate limit + ToS

ORSR has no documented per-IP limit but is a small ministry site; we cap
the adapter at 30 req/min and use `get_with_retry` with `Retry-After`
honoring. RÚZ is similarly undocumented; the same cap applies.

## Test companies

- Volkswagen Slovakia, a.s. — IČO `35757442`, DIČ `SK2020220862`
- Slovenské elektrárne, a.s. — IČO `35829052`
- Tatra banka, a.s. — IČO `00686930`
- Slovnaft, a.s. — IČO `31322832`, DIČ `SK2020372640`

## Status

✅ **LIVE**

| Capability | Source | Notes |
|-----------|--------|-------|
| `search_by_name` | ORSR HTML | windows-1250 decoded explicitly; defensive regex on the result table |
| `lookup_by_identifier` (IČO) | RÚZ JSON | Full entity record with legal form mapping |
| `lookup_by_identifier` (VAT) | RÚZ JSON | Same record via `dic` parameter |
| `fetch_financials` | RÚZ JSON | Annual filings with public PDF URLs; structured XBRL not exposed by RÚZ (PDF text extraction is Phase 2) |

## Known gaps

- ORSR extract pages contain director lists and capital amounts that are
  not pulled today — RÚZ does not expose them, and ORSR HTML parsing is
  brittle (no stable structure). A future enhancement would scrape
  `vypis.asp?P=0` with focused regex to fill `directors` and
  `capital_amount`.
- `idVyrocnychSprav` (annual reports as distinct from financial
  statements) is not yet returned — these are narrative reports rather
  than balance sheets; can be wired later for the risk engine's qualitative
  inputs.
