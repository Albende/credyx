# 🇦🇲 Armenia — State Register of Legal Entities (e-register.moj.am)

## Identifier

- Primary type: `VAT`
- Format: **TIN / ՀՎՀՀ** (Hark Vcharoghi Hashvarkayin Hamar) — 8 digits.
  Sometimes prefixed with `AM`; the adapter strips it. The same number
  serves as the VAT registration ID and the corporate tax ID. The register
  search indexes the TIN, so a bare TIN resolves directly to the company.
- Secondary type: `COMPANY_NUMBER` — the State Registry serial number,
  rendered in `NNN.NNN.NNNNNNN` form (e.g. `286.120.1110041`). Whitespace
  is stripped; otherwise passed through. Also indexed by the search.

## Sources

- https://e-register.moj.am/ — public State Register of Legal Entities
  operated by the Ministry of Justice. Free, no auth. Replaced the old
  `e-register.am` portal (which now redirects here). Flow:
  - `GET /en/search/companies?query=<name|TIN|reg-number>` returns a
    server-rendered list of `<article class="company-search-result">`
    blocks, each linking to `/en/companies/{unique_id}`.
  - `GET /en/companies/{unique_id}` returns the company card: a
    `<dl class="detail-list">` with Company Status, Registration number,
    Registration date, Registration Body, Tax id, Unique identifier, and
    Address. The company name sits in a `.company-title` heading.
- **Auth**: None for the public card. Filed annual financial statements are
  behind the register login and not exposed publicly.
- **Rate limit**: Self-imposed at 30 req/min. The site returns HTTP 429 under
  bursty load; the adapter caps concurrent card fetches (semaphore of 3) and
  honors `Retry-After`.
- **robots.txt / ToS**: public registry-search utility intended for
  third-party use. The adapter sends an identifiable User-Agent and keeps
  volume polite.

### Financial-statement sources (all blocked from outside Armenia)

- https://amx.am/ (Armenia Securities Exchange) and https://cda.am/ (Central
  Depository) — host listed-issuer statements, but the Cloudflare edge
  **IP-bans this environment** (even via FlareSolverr: "Cloudflare has
  blocked this request").
- https://azdarar.am/ — the official public-notifications bulletin where
  joint-stock companies publish audited statements — is **geo-restricted to
  Armenia** ("Connection denied by Geolocation").
- https://cba.am/ (Central Bank, bank/credit-org statements) — also
  **geo-restricted to Armenia**.

## Test companies

Banks and other financial institutions (Ardshinbank, Ameriabank, VivaCell/
K-Telecom) are **not** in this Ministry-of-Justice register — they are
licensed via the Central Bank. Use non-financial entities:

- "UCOM" CJSC (telecom) — TIN `00024873`, reg `286.120.1110041`,
  unique id `37191802`
- "ARDSHIN" LLC — TIN `02925952`, reg `286.110.1454163`, unique id `55415850`
- "SK TELECOM" LLC — unique id `53438060`

## Status

🟡 **Partial — registry only.**

| Capability   | Status                                   |
|--------------|------------------------------------------|
| Name search  | ✅ Live (server-rendered results)        |
| TIN lookup   | ✅ Live (search indexes TIN → card)      |
| Reg-# lookup | ✅ Live (search indexes reg-number)      |
| Financials   | ❌ No free feed reachable outside Armenia |
| Health       | ✅ Probes a known in-register company     |

## Limitations

- **No reachable financial statements.** Annual accounts are filed with the
  State Register but are login-gated; the securities exchange (amx.am / cda.am)
  is Cloudflare IP-banned and the official bulletin / Central Bank
  (azdarar.am, cba.am) are geo-restricted to Armenia. `fetch_financials`
  raises `AdapterNotImplementedError` — no numbers are fabricated. This would
  only be solvable with an Armenian network egress or a registered account.
- **Banks are out of register scope.** The MoJ register search does not return
  banks/insurers/credit organizations; those are supervised by the Central
  Bank of Armenia.
- **Search enrichment costs one card fetch per hit.** The results page carries
  only the name and the company link; TIN, reg-number, status, and address are
  read from each company card. The adapter fetches up to `limit` cards
  concurrently (bounded) to populate identifiers.
- **Addresses stay in Armenian.** Even on the `/en/` card the address value is
  rendered in Armenian script; it is passed through verbatim.

## Recommended next steps

1. If an Armenian egress/proxy becomes available, wire azdarar.am (JSC audited
   statements) and cba.am (bank statements) into `fetch_financials`.
2. Cross-reference each TIN against GLEIF and OpenSanctions on lookup to
   surface LEI links and PEP/sanctions hits up-front.
3. Watch for an official structured/JSON endpoint from the MoJ register to
   replace the HTML scrape.
