# 🇵🇰 Pakistan — SECP + FBR + PSX

## Identifier

- Primary: `Incorporation Number` (SECP) — variable-length numeric ID,
  typically 7 digits, often zero-padded (e.g. `0012345`). Mapped to
  `IdentifierType.COMPANY_NUMBER`.
- Secondary: `NTN` (National Tax Number, FBR) — 7- or 8-digit numeric
  ID, optionally suffixed with `-<check>`. Mapped to
  `IdentifierType.VAT`.
- Tertiary (listed only): PSX trading symbol (e.g. `HBL`, `ENGRO`,
  `PPL`, `LUCK`). Used as a lookup short-circuit for the listed path.

## Sources

- **SECP eServices (Securities and Exchange Commission of Pakistan)** —
  public name search portal:
  https://www.secp.gov.pk/data-and-statistics/eservices/
- **SECP main site** — partial public company info:
  https://www.secp.gov.pk/
- **FBR Online Verification** — partial public NTN/STRN lookup:
  https://e.fbr.gov.pk/
- **PSX Data Portal** — free annual reports for listed companies:
  https://dps.psx.com.pk/
- **Auth**: None claimed; however SECP eServices is fronted by an
  ASP.NET ViewState + CAPTCHA flow that is not driveable without a
  browser-pool. FBR's NTN inquiry is also CAPTCHA-gated.
- **Rate limit**: We self-throttle to 30 req/min. SECP is slow under
  load; respect 5xx with backoff.
- **robots.txt / ToS**: SECP / FBR pages are public-information
  portals; PSX permits non-commercial use of annual reports with
  attribution.

## Test companies

- Habib Bank Limited — PSX `HBL`
- Engro Corporation Limited — PSX `ENGRO`
- Pakistan Petroleum Limited — PSX `PPL`
- Lucky Cement Limited — PSX `LUCK`

## Status

🟡 **Partial** — PSX-listed lookup ✅; SECP Incorporation Number lookup
❌ (eServices session-gated); name search ❌ (CAPTCHA); FBR NTN inquiry
❌ (CAPTCHA); financials ❌ (PSX per-year PDF discovery needs browser).

### What works

- `search_by_name` — matches against a curated PSX-listed company
  table. Returns real company names and PSX source URLs for listed
  entities; raises `AdapterNotImplementedError` otherwise.
- `lookup_by_identifier(COMPANY_NUMBER, <PSX symbol>)` — returns
  `CompanyDetails` (name, legal_form, sector, PSX source URL) for the
  curated set of listed companies.

### What does not work in MVP

- **`search_by_name` for unlisted**: SECP eServices is session-bound
  and gated by a CAPTCHA + ASP.NET ViewState. Raises
  `AdapterNotImplementedError` (→ 501) per the no-mock-data rule.
- **`lookup_by_identifier(COMPANY_NUMBER, <Incorporation Number>)`**:
  SECP per-company detail pages require an authenticated eServices
  session; raised as 501 honestly.
- **`lookup_by_identifier(VAT, <NTN>)`**: FBR Online Verification
  requires CAPTCHA + ViewState; raised as 501.
- **`fetch_financials`**: returns `[]` until the browser pool lands.
  PSX per-year PDF URLs are JS-generated; the listing page is exposed
  via `CompanyDetails.source_url` for manual navigation.

## Recommended next steps

1. Stand up the Playwright browser pool (`packages/adapters/_base/browser.py`)
   so the SECP eServices CAPTCHA + ViewState flow can be driven for
   name search and Incorporation Number lookup.
2. Ingest the SECP "Active Companies" CSV (when published) into Postgres
   nightly so `search_by_name` can serve from a local index without
   touching the eServices portal.
3. Scrape `dps.psx.com.pk/company/<SYMBOL>/financial-reports` to discover
   per-year PDF URLs, then hand off to the PDF text extraction pipeline
   for the LLM context (Pakistani filings follow IAS/IFRS, so a generic
   IFRS parser fits).
4. Phase-2 paid integration option: PACRA / VIS Credit Rating Company
   for credit ratings on bank-rated entities.
5. OpenSanctions screen for Pakistani PEPs and FATF-listed entities is
   already available via `packages/adapters/_global/opensanctions.py`
   — wire into `risk.engine` before the LLM step.
