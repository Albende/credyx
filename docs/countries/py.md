# 🇵🇾 Paraguay — Bolsa de Valores de Asunción (BVA) listed issuers

## Status

- **Live.** Search, lookup and financials all return real data for
  BVA-listed issuers. No API key required.
- Coverage: BVA-listed issuers only (corporates, banks and investment
  funds with registered securities). There is **no free, machine-readable
  national company registry** for private Paraguayan companies — see
  "Why not the tax registry" below.

## Identifier

- Type: `COMPANY_NUMBER` (primary).
- Value: the issuer's **BVA directory code** — the slug of its
  `https://www.bolsadevalores.com.py/emisores/{slug}/` page
  (e.g. `codipsa-2`). This is the stable public identifier BVA exposes;
  the adapter accepts either the bare slug or the full issuer URL.
- The RUC (Registro Único de Contribuyentes) is **not** available on any
  free source (see below), so it is not used as the identifier here.

## Sources

All data comes from the BVA public website
(`https://www.bolsadevalores.com.py/`, WordPress + JetEngine), served over
plain HTTPS with no auth, no key and no bot wall.

- **Name search**: the issuer directory
  `https://www.bolsadevalores.com.py/listado-de-emisores/` lists the
  currently published issuers as `/emisores/{slug}/` links. The adapter
  caches this index (in-memory, per instance), matches the query against
  the slug and the de-slugified name, and then fetches each candidate
  issuer page to resolve its authoritative legal name.
  - The JetEngine listing grid's deeper pages are load-more AJAX pages
    signed with a server-side query signature that cannot be replayed, so
    the searchable index is the set of issuers surfaced on the directory
    page. This covers the actively-listed issuers (including all the test
    companies below); it is not the full historical issuer set.
- **Lookup by identifier**: the issuer detail page
  `https://www.bolsadevalores.com.py/emisores/{slug}/`. The adapter parses
  the legal name (`<title>`), registered address, phone, e-mail, website
  and business sector (`jet-listing-dynamic-field` / `dynamic-link`
  blocks).
- **Financials**: the "Estados Financieros" section of the same issuer
  page. Each filed balance sheet is a dated ZIP under `wp-content/uploads/`
  (e.g. `Balance de Diciembre de 2024` →
  `.../CODIPSA-31_12_2024-CODIPSA.zip`, containing the audited statements
  as an `.xlsm` workbook). The adapter emits one `FinancialFiling` per ZIP
  with the reporting year, `period_end` (parsed from the Spanish
  month/year in the link label), `currency = PYG`, and the real
  `document_url`. It returns filings for the most recent `years` reporting
  years. Numbers are **not** invented — only the filing metadata plus the
  genuine document link are returned.

## Why not the tax registry (DNIT/SET)

The DNIT (ex-SET) RUC infrastructure is not usable key-free from outside
Paraguay:

- `www.dnit.gov.py`, `www.set.gov.py` and `servicios.set.gov.py` are
  **geoblocked** to Paraguayan IPs (connections from elsewhere time out /
  are refused) — FlareSolverr does not help, as this is an IP geoblock,
  not a JS/Cloudflare wall.
- The public RUC consultation service
  (`servicios.set.gov.py/eset-publico/contribuyente/estado`) takes an
  AES-CBC-obfuscated `t3` parameter and returns `{ruc, nombreCompleto, dv}`
  — but only from within PY.
- The full taxpayer registry is published only as bulk ZIP dumps
  ("Listado de RUC con sus equivalencias"), again from the geoblocked host.

If the service is ever deployed from a Paraguayan egress, a DNIT RUC
adapter could be added alongside this one; from the current infrastructure
BVA is the only live free source.

## Test companies

| Company | BVA id (slug) | Notes |
|---------|---------------|-------|
| CODIPSA | `codipsa-2` | Cassava-starch producer. Files annual balance sheets (individual + consolidated). Canonical health-check issuer. |
| Agro Nathura S.A.E. | `agro-nathura-s-a-e` | Agribusiness issuer. |
| AgroAlianza S.A. | `agroalianza-s-a` | Agribusiness issuer. |
| Aseguradora Paraguaya S.A.E.C.A. | `aseguradora-paraguaya-s-a-e-c-a` | Insurer. |

## Verified live

- `search_by_name("codipsa")` → `codipsa-2` / "CODIPSA".
- `lookup_by_identifier(COMPANY_NUMBER, "codipsa-2")` → name, address
  (Avda. Venezuela 2015 c/Avda. Artigas), phone, e-mail
  (contabilidad@codipsa.com.py), website (www.codipsa.com.py), sector.
- `fetch_financials("codipsa-2", years=3)` → 3 filings (Balance Dic-2025,
  Dic-2025 consolidado, Dic-2024) in PYG with real ZIP document URLs.
