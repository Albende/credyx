# 🇫🇷 France — recherche-entreprises.api.gouv.fr (INSEE + INPI)

## Identifier

- Type: `SIREN / SIRET`
- Format: SIREN = 9 digits, SIRET = 14 digits (SIREN + 5).

## Sources

- **Registry + search + lookup**: https://recherche-entreprises.api.gouv.fr
  (docs: https://api.gouv.fr/documentation/api-recherche-entreprises).
  No key. Rate limit 7 req/sec. Open data. Its `finances` block carries filed
  revenue (CA) and net income for recent years.
- **Accounts filings (financials)**: BODACC via the opendatasoft Explore API —
  `https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records`.
  No key. Filter `registre='{siren}' AND familleavis='dpc'` for "dépôts des
  comptes" (annual-accounts filings). Each record gives the closing date
  (`depot.dateCloture`), deposit type, and a per-announcement URL (`url_complete`).
- **Not used**: full comptes annuels PDFs (INPI RNE) sit behind OAuth, so no
  `document_url` is claimed — only the BODACC announcement `source_url`.

## Test companies

- TotalEnergies SE (SIREN 542051180); Carrefour (652014051); Renault (441639465).

## Status

🟢 **Live** — search ✅, lookup ✅, financials ✅ (BODACC accounts-filing metadata
per year + real CA / net-income figures from recherche-entreprises `finances`).
All sources key-free.

**Recommended next step:** Wire INPI RNE OAuth to attach the actual comptes
annuels PDF as `document_url` (currently metadata + figures only).
