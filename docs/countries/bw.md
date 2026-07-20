# 🇧🇼 Botswana — CIPA OBRS + BSE

## Identifier

- Type: `COMPANY_NUMBER` (CIPA registration number).
- Format: `BW` + 11 digits (e.g. `BW00001731678`). Legacy `CO####/#####`
  numbers are mapped to the new format inside the OBRS register.

## Sources

- **CIPA** — https://www.cipa.co.bw
  - Public "Search the Register" on the Foster Moore Catalyst platform:
    `https://www.cipa.co.bw/master/ui/start/CIPARegisterSearch`.
  - Auth: none. The first GET issues an `x-catalyst-registry-session`
    cookie and redirects to a per-session URL. The Angular front end talks
    to that URL over a small JSON command protocol
    (`view-node-set-attribute-value` to fill the search box,
    `view-node-button-click` to submit); the response is a node-state tree
    containing the result cards (name, number, status, entity type,
    registration date, address). **No reCAPTCHA** on this search (the old
    gated form is retired).
  - Rate limit: undocumented; we self-throttle to 30 / min.
- **BSE** (Botswana Stock Exchange) — https://www.bse.co.bw
  - Free JSON disclosure API at `https://apis.bse.co.bw`:
    - `POST /api/v1/x-news-search` with `{"perpage":"5000","search_word":"<ticker>"}`
      returns a listed issuer's X-News disclosures. Each row has `subject`,
      `dateannounced`, `instrument` (ticker/issuer), and `uploaded_to` — a
      real, downloadable PDF (annual reports, integrated reports, audited
      financials).
  - Auth: none. robots-friendly JSON.
- **BURS** (tax authority) — https://www.burs.org.bw
  - Still no public VAT/TIN validation endpoint. Not used.

## Test companies

- Sefalana Holding Company Limited — CIPA `BW00001731678`, BSE ticker `SEFA`.
- First National Bank Botswana — BSE ticker `FNBB`.
- Choppies Enterprises — BSE ticker `CHOPPIES`; CIPA name search "Choppies".
- Letshego Holdings — BSE ticker `LETSHEGO`.

## Status

🟢 **Working** for search, lookup, and (BSE-listed) financials — free, no
API key.

- `search_by_name`: drives the CIPA OBRS register search; returns companies
  (business names are filtered out) with `BW…` numbers, status, and address.
- `lookup_by_identifier`: searches CIPA by the exact `BW…` number and returns
  `CompanyDetails` (legal form, status, incorporation date, registered
  address). Returns `None` if the number is not on the register.
- `fetch_financials`: takes a BSE issuer code / ticker (or listed-company
  name) and returns `FinancialFiling`s for that issuer's annual /
  integrated / audited reports, each with a real downloadable PDF
  (`document_url`), currency `BWP`. Empty for non-listed identifiers
  (only BSE issuers publish free financials).
- `health_check`: probes the CIPA search page and the BSE X-News API.

**Notes / next steps**

1. CIPA financials: private companies file annual returns but do not publish
   accounts, so filed balance sheets are only available for BSE issuers.
2. The BSE disclosure PDFs (often 20–30 MB integrated reports) are ideal
   input for the cross-cutting PDF text-extraction pipeline.
3. Bridging a CIPA number → BSE ticker for listed companies would let
   `fetch_financials` be called with the same identifier as lookup; today
   the caller passes the ticker for the listed-company path.
