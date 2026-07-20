# 🇮🇩 Indonesia — IDX (Indonesia Stock Exchange)

## Identifiers

- **NPWP** (Nomor Pokok Wajib Pajak) — 15-digit tax ID issued by the
  Directorate General of Taxes (Direktorat Jenderal Pajak, DJP).
  Canonical display: `XX.XXX.XXX.X-XXX.XXX`. Mapped to
  `IdentifierType.VAT` and used as the **primary identifier** — IDX
  publishes the NPWP for every listed issuer, so it is directly
  resolvable for free.
- **IDX ticker** (KodeEmiten) — the 2–5 letter exchange code (e.g.
  `TLKM`, `BMRI`). Mapped to `IdentifierType.OTHER` and used as the
  adapter-local stable `id`. Accepted bare or with an `IDX:` prefix.

Normalization strips spaces, dots and dashes; an optional leading `ID`
prefix is accepted on NPWPs.

## Sources

### IDX — Indonesia Stock Exchange

- Base: `https://www.idx.co.id`
- **Auth**: none. Free for all listed issuers. No API key.
- **Bot wall**: both endpoints sit behind Cloudflare, which rejects the
  plain httpx TLS fingerprint with a `403` HTML challenge. Requests are
  routed through the repo's `fetch_with_bot_bypass` (FlareSolverr at
  `http://127.0.0.1:8191`), which returns the JSON wrapped in an HTML
  `<pre>` shell that the adapter unwraps.

Endpoints consumed:

- Company directory (powers search + lookup):
  `/primary/ListedCompany/GetCompanyProfiles?start=0&length=9999&emitenType=s`
  → ~960 issuers, each with `KodeEmiten`, `NamaEmiten`, `NPWP`, `Alamat`,
  sector fields, `Website`, `Telepon`, `Email`, `TanggalPencatatan`.
- Audited financial reports (powers financials):
  `/primary/ListedCompany/GetFinancialReport?year={year}&reportType=rdf&EmitenType=s&periode=audit&kodeEmiten={ticker}&indexFrom=0&pageSize=12&SortColumn=KodeEmiten&SortOrder=asc`
  → per-year results whose `Attachments[]` list real downloadable PDFs
  under `/Portals/0/StaticData/...`. The adapter emits the
  `FinancialStatement-{year}-...pdf` (falling back to `LKFS` / `Laporan
  Keuangan` / `AnnualReport`) as the `document_url`.

### Coverage

- **Listed companies only.** A name search matching nothing on IDX
  returns `[]`; an NPWP that is not a listed issuer resolves to `None`.
- Unlisted Indonesian firms have no free official financial source. AHU
  Online (Kemenkumham) and OSS (BKPM) expose only session-gated /
  paid extracts, and OJK financial data is a paid product — none are
  consumed by the MVP. No fabricated data is ever returned.

## Linking NPWP / ticker → financials

`fetch_financials` accepts an IDX ticker, an `IDX:{ticker}` hint, or a
15-digit NPWP (resolved to its ticker via the IDX directory):

```
adapter.fetch_financials("TLKM", years=3)
adapter.fetch_financials("IDX:BMRI", years=3)
adapter.fetch_financials("010000131093000", years=3)  # Telkom NPWP
```

## Encoding

UTF-8. Indonesian and English business names coexist on IDX records.

## Test companies

| Name | NPWP | IDX ticker |
|------|------|------------|
| PT Bank Mandiri (Persero) Tbk | `01.061.173.9-093.000` | `BMRI` |
| PT Telkom Indonesia (Persero) Tbk | `01.000.013.1-093.000` | `TLKM` |
| Astra International Tbk | `01.302.584.6-092.000` | `ASII` |
| Unilever Indonesia Tbk | `01.001.701.0-092.000` | `UNVR` |

NPWPs above are the values IDX publishes for each issuer (source of
truth); they supersede the earlier values in this doc, which were stale.

## Status

🟢 **Working (listed companies)** — `search_by_name`,
`lookup_by_identifier` (by NPWP or IDX ticker) and `fetch_financials`
(real downloadable audited annual-report PDFs) all return live IDX data
with no API key. Unlisted-firm coverage remains out of scope pending a
paid commercial registry.

**Recommended next steps:**

1. Plug an OJK/IDX XBRL parser into `packages/risk/xbrl_*` so listed
   filings become `structured_data` rather than opaque PDF URLs (the
   IDX report attachments include an `instance.zip` iXBRL package).
2. Ingest an AHU/OSS open-data cache to extend `search_by_name` and
   NPWP/NIB lookup to unlisted companies once a terms-safe feed exists.
