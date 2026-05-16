# 🇲🇲 Myanmar — DICA MyCO + Yangon Stock Exchange (YSX)

## Identifier

- Type: `COMPANY_NUMBER` — DICA Registration Number.
- Format: variable. Historically a 4–7 digit numeric, optionally suffixed
  with `OF` (overseas) or `FC` (foreign). Post-2018 Companies Law
  registrations carry a `YYYYMMDD`-prefixed sequence number
  (e.g. `20180101-1234`). The adapter normalizes to uppercase, strips
  whitespace, drops an optional `MM` prefix, and otherwise preserves the
  input shape.
- Example test companies (all YSX-listed):
  - First Myanmar Investment Public Co., Ltd. — ticker `FMI`.
  - Myanmar Thilawa SEZ Holdings Public Ltd — ticker `MTSH`.
  - Myanmar Citizens Bank Ltd — ticker `MCB`.
  - Ayeyarwaddy Farmers Development Public Co Ltd — ticker `AFD`.

## Sources

- https://www.myco.dica.gov.mm — DICA Online Company Registry (MyCO),
  operated by the Directorate of Investment and Company Administration.
  - **Endpoints used**: `/Companies` (search page) and the backing
    `/Companies/Search` JSON endpoint. The shape is not formally
    documented; we accept both JSON object and list payloads and degrade
    to `[]` on any HTML-only response.
  - **Auth**: No API key. Public search is free.
  - **Rate limit**: Soft, undocumented. Adapter throttles to
    30 req/min.
  - **robots.txt / ToS**: Public; the search index is intended for
    public consultation. Respectful crawling only.
- https://www.ysx-mm.com — Yangon Stock Exchange listed-issuer pages.
  Used solely to synthesize the canonical listed-issuer URL per year
  when the issuer is publicly traded. We probe the symbol landing page
  once and emit `FinancialFiling` records only when the page returns
  200. Unlisted companies receive `[]`.

## Capabilities

- ✅ `search_by_name` — MyCO public search.
- ⚠️  `lookup_by_identifier` — best-effort. Per-company detail pages
  on MyCO are session-bound (ASP.NET ViewState plus a cold-session
  CAPTCHA) and cannot be reliably scraped without a browser pool. We
  return a `CompanyDetails` only when the search endpoint surfaces the
  exact registration number; otherwise `None`. Never fabricates data.
- ⚠️  `fetch_financials` — YSX URLs for the four listed issuers above.
  Unlisted companies return `[]`. No structured ratios are extracted —
  the LLM pipeline must rely on the URL excerpts.

## Sanctions context (read before integrating)

Myanmar is subject to active, evolving sanctions programmes that bear
directly on credit decisions:

- **US OFAC**: Multiple SDN list entries (military regime, MEHL, MEC,
  MOGE, designated state officials). The Burma-related sanctions
  regulations (31 CFR Part 525) apply.
- **UK**: The Myanmar (Sanctions) Regulations 2021 (as amended).
- **EU**: Council Regulation (EU) 401/2013 (as amended).
- **Canada, Australia, Switzerland**: Parallel regimes.

DICA registry data is public and may be ingested freely, but any
downstream credit decision MUST cross-reference OpenSanctions before
approval. This adapter surfaces registry facts only — it performs no
screening of its own. Surface a red flag in `risk.engine` whenever an
`OpenSanctionsClient.screen()` hit returns for a Myanmar entity or any
of its disclosed beneficial owners, particularly military-affiliated
holdings (`MEHL`, `MEC`) and energy SOEs (`MOGE`).

## Status

✅ **Live (best-effort)** — name search via MyCO; identifier lookup
returns a record only when search resolves the registration number;
financials emit YSX URLs for listed issuers only.

**Recommended next steps:**

1. Add Playwright once `packages/adapters/_base/browser.py` lands —
   then MyCO per-company detail pages become tractable.
2. Wire OpenSanctions screening into `risk.engine` so MM lookups
   automatically surface OFAC/UK/EU hits as red flags before the LLM
   call.
3. Track DICA's announced API roadmap (the registry has previously
   referenced a paid commercial API tier — not in scope while
   `_base/proxy.py` and the paid-data feature flag remain unwired).
