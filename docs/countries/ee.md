# 🇪🇪 Estonia — e-Äriregister

## Identifier

- Type: `BUSINESS_ID (registrikood)`
- Format: 8 digits.

## Sources

- **Search + lookup**: Autocomplete JSON service
  `https://ariregister.rik.ee/est/api/autocomplete?q={name|regcode}` — free,
  no contract, no auth. Returns name, registrikood, status, legal address,
  historical names and a company-profile URL. Matches both names and codes.
- **Financials**: public company profile page
  `https://ariregister.rik.ee/est/company/{regcode}` lists every filed annual
  report (majandusaasta aruanne) with fiscal year + period and a direct PDF
  download at `/est/company/{regcode}/file/{fileId}` (returns `application/pdf`).
- **Auth**: none for the above. Detailed structured data (`arireg.detailandmed_v2`)
  and the XML/SOAP services require a signed RIK contract — not used.
- **Rate limit**: none documented; adapter self-throttles at 60/min.
- **robots.txt / ToS**: public open-data surfaces; OK.

## Test companies

- Bolt Technology OÜ (12417834); Veriff OÜ (12932944); Wise (Estonia) OÜ.

## Status

🟢 **Live.** Search, lookup and financials all return real data with no API key.
Financials expose filed annual-report metadata (year, period end, EUR) plus a
real per-company PDF `document_url`. Structured financial figures would require
the paid RIK detailed-data contract or ingesting the bulk annual-report CSVs.
