# 🇹🇳 Tunisia — RNE / BVMT

## Identifier

- Primary: `VAT` → **Matricule Fiscal** (tax id), canonical form
  `1234567/A/M/000`: 7 digits + control letter + category letter +
  establishment letter + 3 establishment digits. Normalised by
  stripping slashes, dashes, dots, and whitespace, then upper-casing
  (e.g. `1234567/A/M/000` → `1234567AM000`... canonical adapter form
  requires `\d{7}[A-Z]{3}\d{3}`). An optional `TN` prefix is dropped.
- Secondary: `COMPANY_NUMBER` → **RNE Number** issued by the Registre
  National des Entreprises. Digit string up to ~12 chars; the registry
  has re-numbered companies since the 2018 reform so length is not
  strictly enforced.

## Sources

- **RNE — Registre National des Entreprises** —
  https://www.registre-entreprises.tn/rne-public/. Public-facing
  single-page application backed by JSON endpoints under
  `/rne-public/api/`. The endpoint paths are **not formally
  documented**; the adapter probes a small set of known variants
  (`/entreprises/search`, `/recherche`, `/companies/search`) and
  surfaces real matches when the JSON shape is recognisable. When the
  registry returns HTML, a session-token wall, or an unparseable
  payload, the adapter raises `AdapterNotImplementedError` rather than
  fabricate records.
  - **Auth**: None for public search; some detail pages require a
    paid-tier B2B account.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.
- **BVMT — Tunis Stock Exchange** — https://www.bvmt.com.tn/. Free
  annual reports and reference documents for the ~80 listed issuers.
  Per-issuer pages are keyed by ticker, not Matricule Fiscal, so the
  MVP adapter cannot enumerate filings by tax id without a separate
  resolver.

## Test companies

- **Banque de Tunisie** — listed on BVMT (ticker `BT`).
- **Tunisie Telecom (Société Nationale des Télécommunications)** —
  state-owned, not listed.
- **SFBT (Société Frigorifique et Brasserie de Tunis)** — listed on
  BVMT (ticker `SFBT`).
- **Délice Holding** — listed on BVMT (ticker `DH`).

## Status

🟡 **DEGRADED** — RNE JSON endpoints are undocumented; the adapter
returns real data when the portal answers in a parseable shape and
raises a deterministic 501 otherwise. BVMT financials are reachable
in principle but require a Matricule → ticker resolver before they can
be surfaced as `FinancialFiling` entries.

**Capabilities**
- `search_by_name` — Best-effort against undocumented RNE JSON
  endpoints. Real matches when the portal responds; otherwise
  `AdapterNotImplementedError`.
- `lookup_by_identifier(VAT, matricule)` — Probes RNE JSON detail
  endpoints. Real `CompanyDetails` when parseable, `None` on 404,
  `AdapterNotImplementedError` when no endpoint variant returns
  structured JSON.
- `lookup_by_identifier(COMPANY_NUMBER, rne)` — Same path as VAT.
- `fetch_financials(matricule)` — Returns `[]` for any well-formed id
  in MVP. Tunisian SARLs are not required to deposit accounts
  publicly, so an empty list is the factual answer for non-listed
  firms; listed-issuer enumeration via BVMT is a follow-up.

**Known gaps / next steps**
- Document a stable RNE JSON contract once a B2B agreement or
  published swagger appears (the new RNE platform is post-2018 and
  the API surface has been evolving).
- Build a Matricule-Fiscal → BVMT-ticker map (small fixed list, ~80
  issuers) to enable `fetch_financials` for listed firms.
- Wire the PDF extraction pipeline (`pypdf` is in `requirements.txt`)
  so BVMT annual reports can populate `pdf_text_excerpts` for the
  LLM.
- Tunisian filings frequently mix French and Arabic; the adapter
  passes through UTF-8 unchanged. The downstream risk engine prompt
  must support bilingual context for these issuers.
