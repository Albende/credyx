# Ghana — GSE issuers (kwayisi + AfricanFinancials); RGD/GRA gated

## Identifier

- Types: `OTHER` (GSE ticker — **primary**), `COMPANY_NUMBER` (RGD
  registration number), `VAT` (GRA TIN).
- **GSE ticker** (`OTHER`): 2–8 alphanumerics, e.g. `MTNGH`, `GCB`, `EGH`,
  `TOTAL`. This is the primary identifier because it is the only one that
  resolves against a free, key-less source.
- RGD format (`COMPANY_NUMBER`): prefix + digits, e.g. `CS123456789`
  (Company limited by Shares), `CG…` (Guarantee), `PS…` (Partnership),
  `BN…` (Business Name). Prefix tags the entity type, then 6–12 digits.
  **Gated** — lookups raise `AdapterNotImplementedError`.
- GRA TIN format (`VAT`): `[C|P]NNNNNNNNNN` — one letter (`C` company,
  `P` person) then 10 digits, e.g. `C0001234567`. Newer individual TINs
  use the Ghana Card PIN (`GHA-NNNNNNNNN-N`); companies keep the legacy
  `C` format. **Gated** — CAPTCHA-protected, raises
  `AdapterNotImplementedError`.

## Sources

- **kwayisi GSE-API** — https://dev.kwayisi.org/apis/gse — key-less JSON.
  - `/equities` — every GSE ticker + last price.
  - `/equities/{ticker}` — issuer profile: legal name, sector, industry,
    registered address, telephone, email, website, shares, market cap.
- **AFX index** — https://afx.kwayisi.org/gse/ — key-less HTML table
  mapping every GSE ticker to its company name (used for name search).
- **AfricanFinancials** — https://africanfinancials.com/company/gh-{slug}/
  — free per-issuer pages listing filed annual reports. Each annual report
  is a Google-Drive-hosted PDF that downloads directly via
  `https://drive.google.com/uc?export=download&id={id}`.
- **RGD / Office of the Registrar of Companies** — https://rgd.gov.gh/,
  https://orc.gov.gh/, https://eregistrar.rgd.gov.gh/ — login-gated search
  shell; certified extracts paid per document. No free API.
- **GRA TIN checker** — https://gra.gov.gh/ — CAPTCHA / session form. No
  free API.
- **Auth**: none required for GSE-API, AFX, or AfricanFinancials.
- **Bot wall**: AfricanFinancials sits behind Cloudflare (`Just a
  moment…`). The adapter fetches it through `fetch_with_bot_bypass`
  (FlareSolverr). The kwayisi hosts are direct httpx.
- **AfricanFinancials ticker differences**: some GSE tickers map to a
  different AfricanFinancials slug — `MTNGH→gh-mtn`, `EGH→gh-ebg`,
  `AADS→gh-aad`. The adapter tries the override first, then the lowercased
  GSE ticker.
- **Rate limit**: none documented; we self-throttle to 30/min.
- **robots.txt / ToS**: RGD forbids automated scraping (not used); the
  kwayisi APIs are published for programmatic use; AfricanFinancials serves
  public listed-issuer pages.

## Test companies (GSE tickers)

- MTN Ghana (Scancom PLC) — `MTNGH`
- GCB Bank PLC — `GCB`
- Ecobank Ghana PLC — `EGH`
- Total(Energies) Petroleum Ghana — `TOTAL`

## Status

**Live (GSE-listed issuers)** — `search_by_name`, `lookup_by_identifier`
(by `OTHER` = GSE ticker), and `fetch_financials` all return real data for
the ~40 GSE-listed companies, which also covers the largest Ghanaian
corporates by market cap. `fetch_financials` returns annual-report filing
metadata (year, `annual_report`, `GHS`, source page) plus a directly
downloadable Google-Drive PDF `document_url`.

Non-listed companies have **no free structured source**: RGD lookup is
login-gated with paid extracts and GRA TIN validation is CAPTCHA-protected,
so `COMPANY_NUMBER` / `VAT` lookups raise `AdapterNotImplementedError`.

**Recommended next steps:**

1. Wire the downloaded annual-report PDFs into the PDF-text extraction
   pipeline so the risk engine gets real financial line items (currently we
   return filing metadata + a downloadable URL, not parsed statements).
2. Phase-2: a logged-in eRegistrar scraping worker (Celery + cookie jar)
   for RGD extracts on non-listed companies — each extract has a
   per-document fee in GHS, so it needs a credit-budget layer first.
3. GRA TIN validation realistically needs paid third-party access or a
   Playwright + CAPTCHA-solving worker — out of scope for the free MVP.
