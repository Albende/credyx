# 🇸🇮 Slovenia — AJPES

## Identifiers

- **Matična številka** (Registration Number) — primary, 10 digits.
  Mapped to `IdentifierType.COMPANY_NUMBER`.
- **Davčna številka** (Tax / VAT number) — `SI` + 8 digits.
  Mapped to `IdentifierType.VAT`. Both forms (with or without the `SI`
  prefix) are accepted on input; normalized output is `SI` + 8 digits.

## Sources

- **AJPES eObjave** — court-register publications.
  https://www.ajpes.si/eObjave/
  Public, no auth. Result rows expose: date, type, company name, matična,
  davčna, Srg number. Used as the canonical identifier-pair source.
- **AJPES JOLP** — public list of annual-report filers.
  https://www.ajpes.si/jolp/
  Public, no auth. Result rows expose: name, street, postcode, city,
  district court, file number. Used to enrich `registered_address`.
- **Auth**: None for the two endpoints above. Individual filing detail
  pages (objava.asp, JOLP company detail, ePRS company detail, FI-PO
  figures) are gated behind a *free-but-registered* AJPES login.
- **Rate limit**: Not formally documented. Adapter throttles to
  30 req/min as a respectful default.
- **robots.txt**: `/robots.txt` only disallows `MJ12bot` from `/fipo/`.

## Test companies

| Company | Matična | Davčna (VAT) |
|---|---|---|
| KRKA, tovarna zdravil, d. d., Novo mesto | 5043611000 | SI82646716 |
| Petrol, d. d., Ljubljana | 5025796000 | SI80267432 |
| Poslovni sistem Mercator, d. d. | 5300231000 | SI45884595 |
| Gorenje, d. o. o. | 5163676000 | — |

Note: 5043591000 (sometimes circulated as Krka's matična) is a typo —
the registry returns the company under 504361**1**000.

## Status

🟡 **Partial** — registry data live, financials deferred.

- `search_by_name`: ✅ via eObjave `Firma=` (returns name + matična + VAT).
- `lookup_by_identifier`: ✅ via eObjave `Maticna=` / `Davcna=`, address
  enriched from JOLP.
- `fetch_financials`: ❌ raises `AdapterNotImplementedError`. The actual
  annual-report PDFs and FI-PO structured figures are behind the free
  AJPES login. Implementing them needs a browser pool + registered
  credentials, slated for Phase 2.
- `health_check`: probes `eObjave/default.asp?s=48`.

## Known limitations

- No directors, share capital, or NACE codes from public endpoints.
- No financial filings without an authenticated session.
- HTML scrape — if AJPES restructures result tables, parsing will degrade
  to empty lists (defensive parsing already in place; tests are
  integration-marked to catch real-world regressions).

## Recommended next step

1. Open a free AJPES user account.
2. Add a cookie-jar session to the adapter so the JOLP `podjetje.asp`
   detail (financial figures) and `objava.asp` individual filings become
   parseable.
3. Wire `pypdf` for the JOLP annual-report PDF text extraction.
