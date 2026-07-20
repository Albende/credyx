# 🇰🇪 Kenya — NSE issuer disclosures (BRS + KRA gated)

## Identifier

- Types: `OTHER` (NSE issuer slug — **primary, free**),
  `COMPANY_NUMBER` (BRS registration number — gated),
  `VAT` (KRA PIN — gated).
- NSE issuer slug: the WordPress post slug of the listed company, e.g.
  `safaricom-plc`, `kcb-group-plc`, `equity-group-holdings`. Returned as
  the `id` of every `search_by_name` match and used for
  `lookup_by_identifier` / `fetch_financials`.
- BRS format: prefix + digits, e.g. `PVT-XXXXXXX`, `CPR/XXXXX`.
- KRA PIN format: `[A|P]NNNNNNNNNL` — one letter (`P` person, `A`
  non-individual), 9 digits, one trailing check letter, e.g. `P051092002G`.

## Sources

- **https://www.nse.co.ke/wp-json/wp/v2/** — Nairobi Securities Exchange
  public WordPress REST API. **No API key.** This is the live data source:
  - `GET /nse_timeline_event?search={name}` → register of ~46 listed
    issuers (title + slug + link). Drives search + lookup.
  - `GET /nse_timeline_event?slug={slug}` → single issuer record.
  - `GET /media?search={name}` → every issuer disclosure PDF (audited /
    unaudited results, annual reports) with title, upload date and a
    direct `source_url` to the PDF on `nse.co.ke/wp-content/uploads/`.
    Drives `fetch_financials`. PDFs download directly (`application/pdf`).
- https://brs.go.ke/ — BRS via eCitizen: **gated** (login + paid extracts,
  ~KES 600/doc). No free JSON search API.
- https://itax.kra.go.ke/ — KRA iTax PIN checker: **gated** (ASP.NET
  ViewState + CAPTCHA).
- **Rate limit**: none documented; self-throttle to 30/min.
- **robots.txt / ToS**: BRS forbids automated scraping; NSE permits
  read-only access to public pages. The WP REST API is public and
  key-free.

## Test companies (NSE issuer slug)

- Safaricom PLC — `safaricom-plc` (search: `Safaricom`)
- Equity Group Holdings — `equity-group-holdings` (search: `Equity Group`)
- KCB Group Plc — `kcb-group-plc` (search: `KCB`)
- East African Breweries — `east-african-breweries` (search:
  `East African Breweries`) — timeline title is the ticker `EABL`, so this
  resolves via the media-index fallback.

## Status

🟢 **Live (NSE-listed issuers)** — `search_by_name`,
`lookup_by_identifier(OTHER, slug)` and `fetch_financials` all return real,
key-free data from the NSE WordPress REST API. `fetch_financials` returns
one filing per fiscal year (audited annual results preferred, interim
otherwise) with a real, downloadable PDF `document_url` and `currency=KES`.

Coverage is the ~46 NSE-listed issuers — the largest KE corporates by
market cap. Non-listed companies remain uncovered: `lookup_by_identifier`
by `COMPANY_NUMBER` (BRS) or `VAT` (KRA) still raises
`AdapterNotImplementedError` because those sources are login/CAPTCHA gated
and paid per extract.

**Recommended next steps:**

1. Wire the filing PDFs into the PDF-extraction pipeline so the risk
   engine gets structured balance-sheet / P&L figures (today it gets
   filing metadata + a downloadable PDF).
2. Phase-2: add a logged-in eCitizen scraping worker for BRS extracts
   (Celery + cookie jar; ~KES 600/doc — needs a credit-budget layer).
3. KRA PIN validation realistically needs paid third-party access — not
   in scope for the free MVP.
