# 🇰🇿 Kazakhstan — adata.kz + stat.gov.kz + KASE

## Identifier

- Type: `VAT` (primary) and `COMPANY_NUMBER` (alias) — both resolve to
  the BIN.
- Format: **BIN** (Бизнес-сәйкестендіру нөмірі / Бизнес-идентификационный
  номер) — exactly **12 digits**. Issued by the Ministry of Justice to
  every legal entity at registration. Natural persons receive an IIN of
  the same width — out of scope here.
- Some external sources prefix the BIN with `KZ`; the adapter strips it.

## Sources

- **adata.kz** — `https://adata.kz/v1/info/bin/{bin}`. Community-built,
  **free** JSON wrapper that surfaces legal-entity records from the
  Bureau of National Statistics. No auth. Unofficial third party, so the
  adapter treats it as best-effort and falls back to a stat.gov.kz URL
  on failure.
- **stat.gov.kz** — Bureau of National Statistics. Publishes the legal-
  entity registry as periodic open-data dumps; no live REST search.
  Used as authoritative `source_url` fallback at
  `https://stat.gov.kz/ru/lawyer-info/?bin={bin}`.
- **kgd.gov.kz** — State Revenue Committee. VAT payer search is partial-
  public and session-bound; not relied on.
- **kase.kz** — Kazakhstan Stock Exchange. Listed-issuer annual reports
  are published as free PDFs under `https://kase.kz/en/issuers/{ticker}/`.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min. adata.kz has no published
  budget; we keep volume polite.
- **robots.txt / ToS**: adata.kz robots.txt is permissive; KASE allows
  read-only access to public issuer pages.

## Test companies

- KazMunayGas (НК "КазМунайГаз" АО) — BIN `020640000327`
- Kazatomprom (НАК "Казатомпром" АО) — BIN `970640000147`
- Kaspi Bank (Kaspi.kz) — BIN `920140000084`
- Air Astana JSC — BIN `011040000284`

## Status

🟡 **Partial — lookup + listed-issuer financials.**

| Capability  | Status                                       |
|-------------|----------------------------------------------|
| Name search | ❌ Not implemented (no free endpoint)        |
| BIN lookup  | ✅ Live via adata.kz (with stat.gov.kz fallback) |
| Financials  | 🟡 KASE-listed issuers only (PDF/HTML URLs)  |
| Health      | ✅ Probes adata.kz with KazMunayGas BIN       |

## Limitations

- **No free name search.** Neither adata.kz nor stat.gov.kz expose a
  public name → BIN endpoint without registration. The adapter raises
  `AdapterNotImplementedError` on `search_by_name`. A follow-up could
  integrate OpenCorporates KZ for fuzzy resolution.
- **adata.kz is community-maintained.** Response shapes have changed
  across versions; the parser accepts both top-level and `data`/
  `company`/`result`-wrapped envelopes and tolerates RU and
  transliterated key names.
- **General financial statements are not public.** Only KASE-listed
  issuers publish accounts freely. For unlisted BINs the adapter returns
  an empty list rather than raising — this is the honest signal.
- **Mixed Cyrillic / Latin / Kazakh script.** Records mix Russian and
  Kazakh (both Cyrillic and Latin since 2017). The adapter forces an
  `Accept-Language: ru,kk;q=0.8,en;q=0.6` header and leaves text in
  whatever script the source returns; no transliteration.
- **No charter-capital data for most entities.** adata.kz only surfaces
  it for a subset; we map `capital_amount` to `None` when absent and
  default the currency to `KZT`.

## Recommended next steps

1. Wire a free name → BIN bridge through OpenCorporates KZ.
2. Ingest the periodic stat.gov.kz legal-entity dump into Postgres so we
   can serve name search without third-party dependence.
3. Once a KASE PDF scraper exists, decode listed-issuer annual reports
   into `structured_data` instead of just surfacing the issuer URL.
4. Add KGD (tax authority) VAT-status probe behind the existing
   adapter — useful as an automatic red flag when a counterparty is
   delisted as a VAT payer.
