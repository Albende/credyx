# 🇪🇪 Estonia — Äriregister

## Identifier

- Type: `BUSINESS_ID (registrikood)`
- Format: 8 digits.

## Sources

- https://www.ariregister.rik.ee/; https://avaandmed.ariregister.rik.ee/
- **Auth**: Live search requires Ariregister contract; bulk open-data dumps are free.
- **Rate limit**: n/a for bulk.
- **robots.txt / ToS**: OK for bulk; live API per contract.

## Test companies

- Bolt Technology OÜ (12417834); Veriff OÜ; Wise (Estonia) OÜ.

## Status

🟡 **Lookup-only stub** linking to inforegister.ee. Live search needs paid contract.

**Recommended next step:** Ingest the periodic Ariregister open-data dump into Postgres for search.
