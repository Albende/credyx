# 🇫🇮 Finland — PRH YTJ (Avoindata)

## Identifier

- Type: `BUSINESS_ID`
- Format: 7 digits + checksum, formatted NNNNNNN-N. Example: 0112038-9 = Nokia Oyj.

## Sources

- Registry (search + lookup): https://avoindata.prh.fi/opendata-ytj-api/v3
- Financials (iXBRL statements): https://avoindata.prh.fi/opendata-xbrl-api/v3
  - `/financials?businessId=` lists filed digital financial periods.
  - `/financial?businessId=&financialDate=` returns the per-company iXBRL document.
- **Auth**: No — both are free public APIs, no key.
- **Rate limit**: 60/min suggested.
- **robots.txt / ToS**: Allowed (CC BY 4.0).

## Test companies

- Search + lookup only (no iXBRL filed): Nokia (0112038-9); Kone (1927400-1); Fortum (1463611-4).
  Listed groups file consolidated IFRS elsewhere, not as iXBRL to the trade register.
- Full flow incl. financials: **Asuntotekniikka Oy (0100379-9)** — 6 iXBRL periods (2020–2025).

## Status

🟢 **Live** — search + lookup + financials all return real data.

`search_by_name` / `lookup_by_identifier` surface the Y-tunnus, current
company name, full registered address (street + postcode + city, city pulled
from the localized `postOffices` array), human-readable legal form and
registration status (from the payload's localized descriptions, EN preferred),
the primary business line NACE code, and the website when present.

Financials come from the PRH Opendata XBRL API, which covers only digital
(iXBRL) statements — about 5% of all filers, mostly SMEs. Large listed groups
are absent here because their IFRS filings live on Nasdaq Helsinki, not the
trade register. `fetch_financials` returns per-period filing metadata with a
`document_url` that downloads the company's real iXBRL instance
(`document_format="xbrl"`, EUR). Structured figures are left unparsed for now;
wiring the CRR/`fi_met` taxonomy into `packages/risk/xbrl_esef.py` is the next
step to surface balance-sheet/P&L numbers.
