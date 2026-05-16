# 🇧🇼 Botswana — CIPA + BURS + BSE

## Identifier

- Type: `COMPANY_NUMBER` (CIPA registration number), also `VAT` (BURS TIN).
- Format: CIPA numbers are alphanumeric (e.g. `CO2010/12345`). No fixed length.

## Sources

- **CIPA** — https://www.cipa.co.bw / https://eservices.cipa.co.bw
  - Auth: none for the public form, but every search is gated by Google
    reCAPTCHA v2. No JSON endpoint. ToS forbids automated access.
  - Verdict: not usable for a free programmatic adapter.
- **BURS** (tax authority) — https://www.burs.org.bw
  - No public VAT/TIN validation endpoint. Verification is in-person /
    eService account only.
- **BSE** (Botswana Stock Exchange) — https://www.bse.co.bw
  - Auth: none. Issuer pages link to annual-report PDFs for free.
  - Rate limit: undocumented; we self-throttle to 30 / min.
  - robots.txt: permissive for issuer pages.

## Test companies

- First National Bank Botswana — BSE ticker `FNBB`.
- Sefalana Holding Company — BSE ticker `SEFA`.
- Choppies Enterprises — BSE ticker `CHOP`.
- Letshego Holdings — BSE ticker `LHL`.

## Status

🔴 **Blocked for general search/lookup**, 🟡 **partial** for BSE-listed
issuers.

- `search_by_name`: raises `AdapterNotImplementedError` — CIPA is
  reCAPTCHA-gated.
- `lookup_by_identifier`: raises `AdapterNotImplementedError` — no free
  CIPA / BURS endpoint.
- `fetch_financials`: returns a BSE issuer-page pointer for the four
  listed tickers above (currency `BWP`); empty for everything else.
- `health_check`: probes `bse.co.bw`.

**Recommended next steps**

1. Wire the cross-cutting PDF pipeline to walk BSE issuer pages and pull
   year-by-year annual-report PDFs.
2. Revisit CIPA once they publish their planned developer API (announced
   under the eServices modernization programme — no ETA).
3. If paid integration is ever in scope, consider a Botswana credit
   bureau (TransUnion BW, Compuscan BW) — outside the free MVP rules.
