# 🇮🇩 Indonesia — AHU Online + OSS + IDX

## Identifiers

- **NPWP** (Nomor Pokok Wajib Pajak) — 15-digit tax ID issued by the
  Directorate General of Taxes (Direktorat Jenderal Pajak, DJP).
  Canonical display: `XX.XXX.XXX.X-XXX.XXX`. Mapped to
  `IdentifierType.VAT`.
- **NIB** (Nomor Induk Berusaha) — 13-digit business identification
  number issued by OSS / BKPM. Mapped to `IdentifierType.COMPANY_NUMBER`.

Normalization strips spaces, dots and dashes; an optional leading `ID`
prefix is accepted on NPWPs.

## Sources

### AHU Online — Direktorat Jenderal AHU, Kemenkumham

- Base: `https://ahu.go.id`
- Public name and NIB search via the portal UI.
- **Auth**: none for the public search; full extracts are paid.
- **JSON API**: not documented and not stable. The site is an Angular
  SPA whose backend endpoints rotate signed tokens — calling them from
  outside the browser session is brittle and arguably against the ToS.
- The adapter therefore raises `AdapterNotImplementedError` for
  `search_by_name` and `lookup_by_identifier` rather than fabricate data.

### OSS — Online Single Submission (BKPM)

- Base: `https://oss.go.id`
- Issues the NIB. A public per-NIB validator exists in the SPA but is
  gated by a session token that requires registration as an OSS user.
- Free anonymous per-NIB JSON lookup is **not available** in the MVP.

### IDX — Indonesia Stock Exchange

- Base: `https://www.idx.co.id`
- Per-symbol annual reports:
  `https://www.idx.co.id/en-us/listed-companies/financial-statements-and-annual-report/?kodeEmiten={symbol}&year={year}`
- Per-symbol company profile:
  `https://www.idx.co.id/en-us/listed-companies/company-profiles/?kodeEmiten={symbol}`
- **Auth**: none. Free for listed issuers.
- **Coverage**: listed companies only. Unlisted Indonesian firms have no
  free official financial source — `fetch_financials` returns `[]`.

### Linking NPWP / NIB → IDX symbol

There is no free open mapping from NPWP to IDX ticker. To request
financials for a listed issuer, callers pass an explicit hint:

```
adapter.fetch_financials("IDX:BMRI", years=5)
```

A bare NPWP / NIB without the hint returns `[]`; an invalid identifier
shape raises `InvalidIdentifierError`. We never invent a ticker.

## Encoding

UTF-8. Indonesian and English business names coexist on AHU records.

## Test companies

| Name | NPWP | IDX ticker |
|------|------|------------|
| PT Bank Mandiri (Persero) Tbk | `01.060.470.7-073.000` | `BMRI` |
| PT Telkom Indonesia (Persero) Tbk | `01.000.013.1-093.000` | `TLKM` |
| PT Astra International Tbk | `01.000.029.7-091.000` | `ASII` |
| PT Unilever Indonesia Tbk | `01.001.701.9-433.000` | `UNVR` |

## Status

🟡 **Partial** — financials best-effort via IDX for listed issuers when
the caller supplies an `IDX:{ticker}` hint. Search and per-identifier
lookup raise `501 not_implemented` because no free, stable, terms-safe
JSON endpoint exists for AHU or OSS.

**Recommended next steps:**

1. Ingest the OSS `pdtt` open-data CSV (when it returns) to build an
   NPWP / NIB → company-name cache so `search_by_name` can answer
   without scraping AHU.
2. Cron-load the IDX listed-companies feed (`/Static/Json/EmitenList.json`,
   public) to maintain an NPWP → ticker mapping; once available, drop
   the `IDX:` hint requirement.
3. Plug an OJK XBRL parser into `packages/risk/xbrl_*` so listed filings
   become `structured_data` rather than opaque URLs.
4. Once a paid InfoCamere-style commercial registry is procured under a
   Phase-2 budget, wire it here behind the same adapter interface.
