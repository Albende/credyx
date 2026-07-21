# 🇽🇰 Kosovo — ARBK (Agjencia për Regjistrimin e Bizneseve të Kosovës)

## Identifier

- Primary type: `COMPANY_NUMBER`
- Format: **Numri Unik Identifikues (NUI)** — the business number printed
  on the register. Modern entities carry a 9-digit NUI (e.g. `810485145`);
  legacy entities carry an 8-digit number, occasionally with a trailing
  letter (e.g. `70123456A`). Issued by ARBK at registration; stable for the
  life of the entity. The adapter accepts both shapes and matches them
  against the ARBK bulk export verbatim.
- Secondary type: `VAT`
- Format: **Numri Fiskal (NF)** — 9 digits (`\d{9}`), issued by the Tax
  Administration of Kosovo (ATK) and doubling as the VAT registration.
  Under the EU VAT-prefix convention it is rendered `XK` + NF; the adapter
  strips the prefix when present. **The free ARBK bulk export is keyed by
  NUI only and does not expose the NF, so `VAT` lookup returns `None`** —
  use `COMPANY_NUMBER` for identifier lookups.

> Note on `XK`: ISO 3166-1 has not formally assigned a code to Kosovo,
> but `XK` is a user-assigned code used by the European Commission, the
> IMF, SWIFT, and most cross-border payments systems. CreditLens uses
> `XK` consistently.

## Sources

- https://arbk.rks-gov.net/ — Kosovo Business Registration Agency,
  operated by the Ministry of Trade and Industry (MTI). Since 2024 the
  portal is a React single-page app backed by a JSON API under
  `/api/api/`. The adapter uses two of its endpoints:
  - `Services/EksportoBiznesetJson?Gjuha=1` — the agency's own bulk
    export: a ZIP containing `Bizneset.json`, the full active + historic
    register (~269k businesses) keyed by NUI, with name, legal form,
    NACE activity, sector, city, status, and employee band. **Search and
    lookup run against this cached dump.**
  - `Services/TeDhenatBiznesit?nRegjistriId=N` — rich per-company detail
    (address, capital, owners, representatives, NACE). Keyed by a
    sequential internal id only obtainable from the Turnstile-walled
    search, so used only as a liveness probe in `health_check`.
- **Auth / signed header**: no API key and no registration. Every call
  carries a `key` header the SPA derives per request: `GET
  /api/api/Home/GetDate` returns the server time, which is AES-128-CBC
  encrypted (key = IV = the ASCII literal `8056483646328769`, PKCS7) and
  base64-encoded. The adapter reproduces this in `_compute_key`.
- **Search endpoint is Cloudflare-Turnstile walled.**
  `Services/KerkoBiznesin` requires a Turnstile token minted in a browser
  and rejects any forged token with 401 — unusable server-side. The bulk
  export is the key-free substitute.
- **Rate limit**: Self-imposed at 30 req/min. The 9 MB export is cached
  in-process for 12 h so name search and lookup do not re-download it.
- **robots.txt / ToS**: the bulk export is a public, agency-published data
  product intended for third-party reuse. The adapter sends a clearly
  identifiable User-Agent and keeps volume polite.

## Encoding caveat

The `EksportoBiznesetJson` payload has lost its non-ASCII letters at the
source — Albanian/Serbian diacritics (ë, ç, š, đ) arrive as the Unicode
replacement character `�` (e.g. `Prishtin�`, `Shoq�ri aksionare`). This is
a defect in ARBK's export, not the adapter. Name matching folds both query
and target to bare ASCII so lookups survive it; stored values keep the
source text as-is rather than guess the original letters.

## Test companies

- Raiffeisen Bank Kosovo J.S.C. — among the largest banks in Kosovo;
  used for live-search smoke tests.
- Posta dhe Telekomi i Kosovës Sh.A. (PTK) — state-owned incumbent
  telecom operator.
- Banka Ekonomike Sh.A. — domestic commercial bank.
- ProCredit Bank Kosovo Sh.A. — SME-focused commercial bank.

Verified live (July 2026) from the ARBK export:

- Raiffeisen Bank Kosovo J.S.C. SH.A. — NUI `810485145` (active,
  Prishtinë, NACE 6492).
- ProCredit Bank SH.A. — NUI `810487191` (active).

Integration tests search by name and validate result shape; the unit
tests pin the `_compute_key` signing vector so the API contract is
guarded without network access.

## Status

🟡 **Partial — registry only (search + lookup live, no financials).**

| Capability        | Status                                    |
|-------------------|-------------------------------------------|
| Name search       | ✅ Live via ARBK bulk export (JSON)       |
| COMPANY_NUMBER    | ✅ Live via ARBK bulk export (JSON)       |
| VAT (NF) lookup   | ⚪ Not resolvable — NF absent from export  |
| Financials        | ❌ No free machine-readable source exists  |
| Health            | ✅ Probes arbk.rks-gov.net `/api/api`     |

## Limitations

- **No public financial statements — anywhere free and machine-readable.**
  Verified July 2026: ARBK exposes no financial data; the Central Bank of
  Kosovo (bqk-kos.org) publishes only its own statements and sector
  aggregates, not individual banks' filings; the Kosovo Council for
  Financial Reporting (KKRF / POB) registers auditors but does not publish
  filed statements; Kosovo has no stock exchange; and the ATK open-data
  programme covers taxpayer registration, not accounts. Commercial banks
  publish audited statements only on their own websites (no common
  registry). `fetch_financials` therefore returns `[]` rather than
  fabricate data or scrape per-company sites.
- **VAT (NF) lookup unsupported.** The free bulk export is keyed by NUI and
  omits the fiscal number, so `lookup_by_identifier(VAT, …)` returns
  `None`. The `TeDhenatBiznesit` detail endpoint carries the NF but is
  reachable only via a sequential id minted by the Turnstile-walled search.
- **Lookup detail is export-grade.** Because the rich `TeDhenatBiznesit`
  endpoint is gated behind the Turnstile search, `lookup_by_identifier`
  returns what the bulk export carries — name, legal form, status, city,
  NACE code, sector, and employee band — not registered street address,
  share capital, or directors.
- **Currency defaults to EUR.** Kosovo unilaterally adopted the euro in
  2002; Kosovar company figures are denominated in EUR.

## Recommended next steps

1. Solve `Services/KerkoBiznesin`'s Cloudflare Turnstile via a headless
   browser (`packages/adapters/_base/browser.py`) to obtain the sequential
   `nRegjistriId`, then call `Services/TeDhenatBiznesit` to enrich
   `lookup_by_identifier` with address, capital, owners, and directors.
2. Cross-reference each NUI/NF against GLEIF (very few Kosovo LEIs exist)
   and OpenSanctions on lookup to surface sanctions/PEP hits up-front.
3. For the banking subset, wire per-bank audited statements from each
   bank's own site (BQK links but does not host them) if bank-level credit
   analysis becomes a priority — there is no general registry to build on.
