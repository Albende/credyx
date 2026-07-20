# 🇸🇦 Saudi Arabia — GLEIF registry + Saudi Exchange (Tadawul)

## Identifiers

- **CR Number** (Commercial Registration) — 10 digits, mapped to
  `IdentifierType.COMPANY_NUMBER`. Common prefixes:
  - `1010xxxxxx` — Riyadh-issued main CR (e.g. 1010150269 STC).
  - `2052xxxxxx` — Eastern Province (e.g. 2052101150 Saudi Aramco).
  - `4030xxxxxx` — Jeddah / Makkah (e.g. 4030001588 Saudi National Bank).
  - GLEIF stores the CR verbatim in `entity.registeredAs` under
    registration authority `RA000513` (Saudi Ministry of Commerce), which
    is what the adapter keys lookups on.
- **VAT** — 15 digits beginning with `3`. May be presented with an
  EU-style `SA` prefix; adapter strips it.
- **700 ID** — Establishment number used by GOSI / Ministry of Labour,
  10 digits beginning with `7`. Shares the `COMPANY_NUMBER` slot.

## Sources

- **GLEIF** — https://api.gleif.org/api/v1 (free, no key, JSON:API).
  - `search_by_name`: `filter[fulltext]` scoped to
    `filter[entity.legalAddress.country]=SA`. Fulltext matches Arabic
    legal names through their transliterated forms, so an English query
    (e.g. "SABIC", "Saudi Basic Industries") resolves the entity whose
    `legalName` is Arabic.
  - `lookup_by_identifier` (CR): `filter[entity.registeredAs]=<CR>` →
    LEI → full record (legal name, LEI, address, status).
- **Saudi Exchange (Tadawul) main-market company profile** —
  https://www.saudiexchange.sa/wps/portal/saudiexchange/hidden/company-profile-main/
  - TASI-listed issuers publish server-rendered annual **Balance Sheet /
    Statement of Income / Cash Flows** tables (figures in SAR '000).
  - Behind Akamai + a rotating WebSphere portal token, so we go through
    `fetch_with_bot_bypass` (FlareSolverr). The token is never hard-coded:
    every profile page embeds the full issuer directory with a
    currently-valid profile link per issuer, which we harvest and follow.
  - **CR → Tadawul symbol** bridge: rank the 399-issuer directory by name
    overlap with the entity's GLEIF name variants; an exact match to an
    issuer's unique display name is trusted, weaker matches are confirmed
    only if the CR appears in the profile page text.
- **ZATCA VAT validator** — https://zatca.gov.sa/en/eServices — reCAPTCHA
  gated, no structured JSON. VAT lookup raises `AdapterNotImplementedError`.
- **Wathq** (https://api.wathq.sa/) — official MCI B2B data API but paid;
  out of scope per non-negotiable rule #2.

## Test companies (REAL)

| Company | CR (GLEIF registeredAs) | TASI | Verified |
|---------|-------------------------|------|----------|
| Saudi Telecom Company (STC) | `1010150269` | 7010 | search + lookup + financials |
| Saudi Basic Industries Corp. (SABIC) | `1010010813` | 2010 | search + lookup + financials |
| Saudi Arabian Oil Company (Aramco) | `2052101150` | 2222 | lookup (name too generic in GLEIF for the symbol bridge) |
| Saudi National Bank (SNB) | `4030001588` | 1180 | lookup |

> Note: earlier drafts of this doc listed Aramco as `2052101140` and SNB
> as `1010008668`; GLEIF holds `2052101150` and `4030001588` respectively.

## Status

🟢 **Live — registry + listed-company financials, all free / key-less.**

**Capabilities**

- `search_by_name` — GLEIF fulltext (SA-scoped). Returns `CompanyMatch`
  with LEI + CR identifiers.
- `lookup_by_identifier`:
  - `COMPANY_NUMBER` (CR / 700) — GLEIF record for the entity; `None` if
    the CR is not in GLEIF. No fabricated fields.
  - `VAT` — raises `AdapterNotImplementedError` (no free structured
    source; ZATCA is reCAPTCHA-gated).
- `fetch_financials` — for TASI-listed issuers, real annual
  Balance Sheet / Income / Cash Flow figures scraped from the Saudi
  Exchange profile, one `FinancialFiling` per fiscal year with the
  reported figures in `structured_data` (currency SAR, unit '000).
  Returns `[]` when the CR is not in GLEIF or the entity is not listed.

**Known gaps / next steps**

1. Unlisted-company financials — no free source (Wathq is paid).
2. Aramco-style symbol resolution: GLEIF's legal name ("Saudi Arabian Oil
   Company") shares no distinctive token with the Tadawul display ("SAUDI
   ARAMCO"), so the name bridge can't confirm it without a CR echo on the
   page. A CR-indexed issuer directory would close this.
3. VAT enrichment if a key-less ZATCA path appears.
