# 🇬🇧 United Kingdom — Companies House

## Identifier

- Type: `COMPANY_NUMBER`
- Format: 8-character alphanumeric, numeric values zero-padded (e.g. 00102498 = BP).

## Sources

- https://developer.company-information.service.gov.uk
- **Auth**: Yes — `UK_COMPANIES_HOUSE_API_KEY` (free, instant signup).
- **Rate limit**: 600 req / 5 min.
- **robots.txt / ToS**: ToS allows API use; web scraping discouraged.

## Test companies

- BP p.l.c. (00102498); HSBC Holdings plc (00617987); Vodafone Group plc (01833679).

## Status

✅ **Live** — search + lookup + financials (PDF document URLs).

**Recommended next step:** Plug in pypdf/pdfplumber extraction so the LLM can read filed accounts text.
