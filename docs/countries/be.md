# Belgium — KBO/BCE + NBB CBSO

## Identifier

- Primary type: `VAT` (Belgian VAT == enterprise number with `BE` prefix).
- Also accepted: `COMPANY_NUMBER` (the bare 10-digit enterprise number).
- External format: `NNNN.NNN.NNN` (UI-style, dot-separated, 10 digits).
- Internal format used by APIs: `0XXXXXXXXX` (bare 10 digits, must start with `0` or `1`).
- The adapter normalizes any of `BE0417497106`, `0417.497.106`, `0417 497 106`, `417497106` to the bare 10-digit form.

## Sources

### Registry — KBO/BCE Public Search (HTML)

- URL: `https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?ondernemingsnummer={n}&lang=en`
- Auth: none.
- Rate limit: not published; adapter throttles itself to 30 req/min.
- robots.txt / ToS: scraping the public page is permitted for individual look-ups; bulk extraction should use the [KBO Open Data dump](https://kbopub.economie.fgov.be/kbo-open-data/) (separate path, not used by this adapter).
- Parsed fields: name, status, legal form, registered address, start date, capital (EUR), NACE codes, directors.

### Financials — NBB Central Balance Sheet Office "Consult" (JSON)

The CBSO public consultation SPA is backed by anonymous JSON endpoints under `consult.cbso.nbb.be/api/rs-consult/` plus a public PDF download under `/api/external/broker/public/deposits/pdf/`. These do **not** require the paid `NBB-CBSO-Subscription-Key` developer-portal credentials — that key is for the bulk webservice API (`ws.cbso.nbb.be`), which is out of scope for this MVP.

| Purpose | Endpoint |
|---|---|
| Filings list | `GET /api/rs-consult/published-deposits?enterpriseNumber={n}&page=0&size=100&sort=periodEndDate,desc` |
| Company details (NBB cache) | `GET /api/rs-consult/companies/{n}/EN` |
| Name search | `GET /api/rs-consult/companies/search?companyName={q}&language=EN&postalCode=&phonetic=false&exact=false` |
| PDF download | `GET /api/external/broker/public/deposits/pdf/{depositId}` (requires `Accept: */*`, not `application/pdf`) |
| Health probe | `GET /api/rs-consult/version` |

PDF documents are returned as `application/octet-stream`, free of charge, no auth, no CAPTCHA.

## Test companies

| Company | VAT | Enterprise number |
|---|---|---|
| Anheuser-Busch InBev | BE0417497106 | 0417.497.106 |
| Solvay S.A. | BE0403091220 | 0403.091.220 |
| Proximus | BE0202239951 | 0202.239.951 |
| Colruyt | BE0400378485 | 0400.378.485 |

## Status

- Lookup by identifier: **LIVE** (KBO HTML scrape).
- Filings: **LIVE** (NBB CBSO published-deposits JSON + free PDF download).
- Name search: **PARTIAL** — uses NBB CBSO `companies/search`, which only matches entities that have at least one filed annual account. Pure-KBO free-text search (`zoeknaamfonetischform.html`) is protected by CAPTCHA and intentionally not scraped.

## Limitations

- KBO does not expose structured XBRL/iXBRL filings; all annual accounts come as PDF. Structured ratio extraction requires the PDF text-extraction pipeline (`pypdf` + Celery worker) once it is wired in.
- Name search will not return entities that have never filed accounts with the NBB (e.g. recently incorporated companies, sole proprietorships exempt from filing).
- Shareholders are not parsed — KBO public page does not list them.
- Directors are extracted from the KBO "Functions" table but only the names/roles/appointment dates that are visible; nationality and birth date are not in the public record.

## Why not the developer-portal NBB API

`https://ws.cbso.nbb.be/authentic/legalEntity/{n}/references` is the documented "official" route and is technically free, but it requires an `NBB-CBSO-Subscription-Key` issued through the Azure API Management developer portal after a manual approval step. The public `rs-consult` endpoints used here deliver identical data without that registration friction, so they are preferred for the MVP.
