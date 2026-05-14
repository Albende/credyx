# 🇳🇱 Netherlands — KvK Handelsregister

## Identifier

- Type: `KVK`
- Format: 8 digits. Example: 17014545 = ASML Holding N.V.

## Sources

- https://developers.kvk.nl/
- **Auth**: Yes — `NL_KVK_API_KEY`. Test env is free; production is paid.
- **Rate limit**: 60 req/min on test.
- **robots.txt / ToS**: Per KvK ToS — API only.

## Test companies

- ASML (17014545); Royal Philips (17001910); Heineken (33011433).

## Status

🟡 **Degraded** — needs API key. Lookup + search work; financials require deposited-accounts (paid) integration.

**Recommended next step:** Move to KvK production tier + integrate `gedeponeerde jaarrekeningen` retrieval.
