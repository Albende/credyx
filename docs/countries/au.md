# 🇦🇺 Australia — ABN Lookup (Australian Business Register)

## Identifiers

- Primary: `VAT` — ABN (Australian Business Number, 11 digits). ABN is
  Australia's GST/VAT identifier and the canonical key in ABR.
- Secondary: `COMPANY_NUMBER` — ACN (Australian Company Number, 9 digits)
  issued by ASIC. ACN is embedded in the ABN for incorporated companies.

ABNs carry a check digit. Validation: subtract 1 from the first digit,
multiply each digit by weights (10,1,3,5,7,9,11,13,15,17,19), sum, and
verify the total is divisible by 89.

## Sources

- ABN Lookup web services: https://abr.business.gov.au/json/
  - `MatchingNames.aspx?name=&maxResults=&guid=&callback=callback`
  - `AbnDetails.aspx?abn=&guid=&callback=callback`
  - `AcnDetails.aspx?acn=&guid=&callback=callback`
- Public lookup page (no auth): https://abr.business.gov.au/ABN/View/{abn}
- **Auth**: Yes — `AU_ABN_LOOKUP_GUID` (free GUID, register at
  https://abr.business.gov.au/Tools/WebServices).
- **Rate limit**: Not strictly documented; we throttle to 120 req/min.
- **Wrapper**: Responses are JSONP — `callback({...});`. We strip the
  wrapper before `json.loads`.
- **robots.txt / ToS**: ABN Lookup ToS permits programmatic use under
  the issued GUID.

## Test companies

- BHP Group Limited — ABN `49004028077`
- Commonwealth Bank of Australia — ABN `48123123124`
- Woolworths Group Limited — ABN `88000014675`
- Telstra Corporation Limited — ABN `33051775556`

## Status

🟡 **PARTIAL** — registry search + lookup are live. Financials are NOT
implemented.

## Financials — why not implemented

- ABR does not publish financial statements at all.
- ASIC sells company documents (annual reports, financial statements) at
  AUD ~$40 per filing via Company Search; there is no free official
  bulk source.
- ASX listed-company XBRL is published via the ASX Announcements page,
  which is not bulk-accessible and is generally one-shot PDFs.

Per the project's non-negotiable rule #1 (no mock data) and rule #2 (no
paid APIs in MVP), `fetch_financials` raises
`AdapterNotImplementedError("AU financials require paid ASIC search —
Phase 2")`. `health_check` surfaces `capabilities.financials = False`.

**Recommended next step:** Integrate ASIC Company Search behind a feature
flag once a paid tier is approved, or build an ASX Announcements PDF
scraper for the (smaller) universe of listed entities.
