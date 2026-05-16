# 🇧🇭 Bahrain — MoIC + Bahrain Bourse

## Identifier

- Type: `COMPANY_NUMBER` (CR Number — Commercial Registration issued by
  the Ministry of Industry and Commerce).
- Type: `VAT` — 15-digit NBR (National Bureau for Revenue) VAT account
  number, beginning with `2`.
- For Bahrain Bourse-listed firms `fetch_financials` accepts the ticker
  symbol (e.g. `BATELCO`, `AUB`, `ALBH`, `GFH`) as `company_id`.

## Sources

- **MoIC Bahrain** — https://www.moic.gov.bh/
  - Auth: none, but the public CR portal is form-driven and does not
    expose a free structured JSON/REST API.
  - Status: **not usable** for deterministic search / identifier lookup
    in MVP.
- **NBR Bahrain VAT validator** — https://www.nbr.gov.bh/
  - Form-based public lookup; no free structured endpoint.
- **Bahrain Bourse** — https://www.bahrainbourse.com/
  - Auth: none. Per-issuer disclosure pages at
    `/issuer-profile/{TICKER}` link to free annual reports (PDF).
  - Rate limit: respectful crawler — capped at 30/min.
  - robots.txt / ToS: public investor disclosures, allowed.

## Test companies

- Bahrain Telecommunications Company (Batelco) — `BATELCO`
- Ahli United Bank — `AUB`
- Aluminium Bahrain (Alba) — `ALBH`
- Gulf Finance House — `GFH`

## Status

🔴 **Blocked / Partial** —
- `search_by_name` ❌ — raises `AdapterNotImplementedError` (no free
  MoIC search API).
- `lookup_by_identifier` ❌ — raises `AdapterNotImplementedError` for
  both `COMPANY_NUMBER` and `VAT`.
- `fetch_financials` 🟡 — returns a single Bahrain Bourse landing URL
  pointer for listed issuers; for unlisted companies it returns `[]`.
- `health_check` probes `bahrainbourse.com`.

**Recommended next step:** add a Playwright-driven scraper for MoIC's
public CR lookup once the browser-pool infrastructure (Phase 2) lands,
and parse Bahrain Bourse per-issuer disclosure pages to extract
individual PDF annual reports by year.
