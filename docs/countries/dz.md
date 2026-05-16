# 🇩🇿 Algeria — CNRC / DGI / SGBV

## Identifier

- Primary: `VAT` → **NIF (Numéro d'Identification Fiscale)**, 15
  digits. Normalised by stripping whitespace and dashes; an optional
  `DZ` prefix is dropped. Regex: `^\d{15}$`.
- Secondary: `COMPANY_NUMBER` → **RC (Registre de Commerce)** number
  issued per Wilaya by the CNRC, e.g. `16/00-0123456 B 09`. Format
  varies by tribunal so the adapter only enforces non-empty after
  whitespace normalisation and a permissive alphanumeric/separator
  check.

## Sources

- **CNRC — Centre National du Registre du Commerce** —
  https://sidjilcom.cnrc.dz/. The "Sidjilcom" portal exposes partial
  public access to the RC index but the structured search/lookup
  endpoints are session-gated (cookie + CAPTCHA) and the JSON layer is
  not documented. No free machine-readable contract is published.
- **DGI — Direction Générale des Impôts** —
  https://www.mfdgi.gov.dz/. Provides an NIF validator behind a public
  HTML form. Response is HTML-only and requires a fresh session token
  per request; no free JSON contract.
- **SGBV — Bourse d'Alger** — https://www.sgbv.dz/. Free per-issuer
  pages for the handful of listed companies. Pages are keyed by ticker,
  not NIF / RC, so MVP cannot enumerate filings from a tax id alone.
  - **Auth**: None for public pages.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.

## Test companies

- **Alliance Assurances** — SGBV listed (ticker `ALL`).
- **Saidal Group** — SGBV listed (ticker `SAI`); state pharma.
- **Eriad Setif** — SGBV listed (ticker `ERS`); grain processing.
- **NCA-Rouiba** — SGBV listed (ticker `NCA`); beverage producer.

## Status

🟡 **DEGRADED** — CNRC and DGI are session-gated; the adapter refuses
to fabricate matches and surfaces `AdapterNotImplementedError` for any
search or identifier lookup attempt. SGBV exposes listed-issuer pages
in principle but requires a NIF → ticker resolver before filings can
be enumerated, so `fetch_financials` returns `[]` for any well-formed
identifier (matches the FR / MA convention).

**Capabilities**
- `search_by_name` — `AdapterNotImplementedError`: Sidjilcom search is
  session-gated; no free JSON endpoint.
- `lookup_by_identifier(VAT, nif)` — Normalises the 15-digit NIF then
  raises `AdapterNotImplementedError`: DGI validator is not a free API.
- `lookup_by_identifier(COMPANY_NUMBER, rc)` — Normalises the RC then
  raises `AdapterNotImplementedError`: Sidjilcom detail pages are
  session-gated.
- `fetch_financials(nif|rc)` — Returns `[]` for any well-formed
  identifier. Non-listed Algerian SPA/SARLs are not required to deposit
  accounts publicly, so an empty list is the factual answer for the
  vast majority; listed-issuer enumeration via SGBV is a follow-up.

**Known gaps / next steps**
- Build a NIF / RC → SGBV-ticker resolver (small fixed list — fewer
  than ~10 active issuers) so `fetch_financials` can return real
  annual-report PDFs for listed firms.
- Wire the PDF extraction pipeline (`pypdf` is in `requirements.txt`)
  so SGBV annual reports populate `pdf_text_excerpts` for the LLM.
- Re-evaluate CNRC Sidjilcom once / if it publishes a stable JSON
  contract; a paid B2B subscription would unlock full registry data
  but is out of scope for the free-MVP rule.
- Algerian filings frequently mix French and Arabic; the adapter
  passes through UTF-8 unchanged. The downstream risk engine prompt
  must support bilingual context for Algerian issuers.
