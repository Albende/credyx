# 🇫🇷 France — recherche-entreprises.api.gouv.fr (INSEE + INPI)

## Identifier

- Type: `SIREN / SIRET`
- Format: SIREN = 9 digits, SIRET = 14 digits (SIREN + 5).

## Sources

- https://api.gouv.fr/documentation/api-recherche-entreprises
- **Auth**: No key required.
- **Rate limit**: 7 req/sec (documented).
- **robots.txt / ToS**: Open data — allowed.

## Test companies

- TotalEnergies SE (SIREN 542051180); Carrefour (652014051); Renault (441639465).

## Status

🟡 **Partial** — search + lookup ✅; financials require INPI OAuth (`comptes annuels`) — not in MVP.

**Recommended next step:** Wire INPI OAuth to fetch `comptes annuels` PDFs.
