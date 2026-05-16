# 🇧🇾 Belarus — EGR (Unified State Register)

## Identifier

- Type: `COMPANY_NUMBER` (primary) and `VAT` — both point to the same
  number, the **UNP** (Учетный номер плательщика / Account number of
  the payer). 9 digits. Sometimes written with a `BY` prefix; the
  adapter strips it. The UNP serves simultaneously as the EGR
  registration number, the tax ID, and the VAT registration ID.

## Sources

- https://egr.gov.by/ — public portal of the Unified State Register of
  Legal Entities and Individual Entrepreneurs, run by the Ministry of
  Justice. Free, no auth.
- JSON endpoints used by this adapter (under
  `https://egr.gov.by/api/v2/egr/`):
  - `getShortInfoByRegNum/{unp}` — combined short record.
  - `getBaseInfoByRegNum/{unp}` — fallback for status / registration
    date.
  - `getAddressByRegNum/{unp}` — registered legal address.
  - `getJurNamesByREGNUM/{unp}` — alternative name endpoint.
  - `getJurNamesByJurNamePart/{name}` — name-substring search.
- https://www.nalog.gov.by/ — Ministry of Taxes & Duties (MNS); UNP
  validator only via an interactive web form, not relied on here.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min; the portal has no
  published budget.
- **robots.txt / ToS**: `egr.gov.by/robots.txt` is permissive; the
  portal is a public statutory registry. We send a clearly identifiable
  User-Agent and keep volume polite.

## Financials

Belarus has **no free centralized financial-statements dataset**:

- Annual accounts of LLCs / OAOs / UPs are filed with the Ministry of
  Finance and Belstat (National Statistical Committee), but neither
  agency exposes a free per-company query.
- Listed-issuer reports appear sporadically on the Belarusian Currency
  and Stock Exchange (BCSE / bcse.by) as PDFs — out of scope for the
  free MVP.
- Paid mirrors (e.g., Spark Belarus) wrap the same MoF source.

`fetch_financials` therefore returns `[]` for every company. Per the
MVP rule we do **not** fabricate periods.

## Test companies

- Belaruskali OAO — UNP `600122610`
- BelAZ OAO — UNP `600354898`
- MTS Belarus (СООО «Мобильные ТелеСистемы») — UNP `800013355`
- Belarusbank ASB — UNP `100325912`

## Status

🟡 **Partial — registry only.**

| Capability  | Status                          |
|-------------|---------------------------------|
| Name search | ✅ Live (EGR JSON)              |
| UNP lookup  | ✅ Live (EGR JSON)              |
| Financials  | ❌ Not published centrally      |
| Health      | ✅ Probes Belaruskali UNP       |

## Limitations

- **No public financial statements.** See above. `fetch_financials`
  returns an empty list rather than raising; this allows the risk
  engine to surface a clear "no filings available" signal instead of a
  501.
- **JSON schema drift.** EGR has renamed Cyrillic-prefixed keys
  (`vnaim`, `vnaimsostgo`, `vnaimop`, `vpadres`, …) between portal
  refreshes. The adapter matches loosely on a small allowlist of known
  variants and falls back to scanning multiple nested objects.
- **Geo-limited responses.** The portal occasionally rate-limits or
  challenges requests originating outside Belarus. The adapter honors
  `Retry-After` via `get_with_retry`; persistent blocks should be
  treated as `BLOCKED` and reported here.
- **Sanctions context.** Several large Belarusian entities (Belaruskali,
  BelAZ, Belarusbank) are subject to EU / UK / US sanctions. The
  registry data is factual and non-sanctioned; downstream consumers
  must run OpenSanctions screening before any credit decision.

## Recommended next steps

1. Wire OpenSanctions screening into the BY risk pipeline (Belarus is a
   high-risk sanctions jurisdiction in 2026).
2. Add a BCSE PDF scraper to surface filings for the small number of
   publicly listed Belarusian issuers.
3. Investigate whether MoF publishes nightly XML dumps of basic
   accounting data for any sector (currently only aggregated stats on
   belstat.gov.by).
