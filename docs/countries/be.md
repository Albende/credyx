# 🇧🇪 Belgium — KBO/BCE

## Identifier

- Type: `OTHER (enterprise number)`
- Format: 10 digits formatted NNNN.NNN.NNN.

## Sources

- https://kbopub.economie.fgov.be/
- **Auth**: Free static open-data dump; live search via public web only.
- **Rate limit**: n/a (bulk).
- **robots.txt / ToS**: Allowed.

## Test companies

- AB InBev (0417.497.106); UCB (0403.053.608); Solvay (0403.091.220).

## Status

🔴 **Not yet wired** — KBO open-data CSV dump is the right ingestion path.

**Recommended next step:** Ingest the KBO CSV dump nightly and expose search via Postgres.
