# 🇨🇦 Canada — Corporations Canada register JSON API + SEC EDGAR

## Identifier

- Type: `COMPANY_NUMBER` — the federal register's `corporationId` (bare digits,
  5–8 long). Historically displayed with a cosmetic trailing check digit
  (`426160-7`); the adapter strips the dash. This is the value keyed by the
  register JSON API, **not** the old display number.
- Also accepted: `VAT` — the 9-digit Business Number stem (from a full BN15
  like `847871746RC0001`). Resolvable key-free via the same register JSON
  endpoint on its 9-digit stem.
- `OTHER` is reserved (no direct lookup).

## Sources

- **Corporations Canada** — Innovation, Science and Economic Development Canada.
  Base host `https://ised-isde.canada.ca`.
  - **Name search**: `POST /cc/lgcy/fdrlCrpSrch.html?locale=en_CA` with form
    field `corpName`. Server-rendered HTML result rows link to
    `fdrlCrpDtls.html?corpId=N` and carry the name + status; the adapter parses
    them. No session cookie required.
  - **Record JSON API** (search + lookup source of truth):
    `GET /cc/lgcy/api/corporations/{corporationId}.json?lang=eng`. The same path
    also resolves a 9-digit Business Number. Returns a two-element array
    (`[record, null]` for `lang=eng`). A not-found id returns **HTTP 200** with
    `["could not find corporation N", "..."]` — the adapter treats that as
    `None`. Fields: `corporationNames`, `status`, `act`, `adresses`,
    `businessNumbers`, `annualReturns`, `activities` (incorporation /
    amalgamation / dissolution dates).
  - **Auth**: No. **Public plan**: 60 hits/min (adapter throttles to match).
- **SEC EDGAR** — `https://www.sec.gov` + `https://data.sec.gov`. Financial
  filings for Canadian issuers that cross-list on US exchanges. The adapter maps
  the register's legal name to a CIK via `company_tickers.json`, confirms the
  filer is Canadian (a Canadian province location code, a `Canada` address
  descriptor, or a 40-F/20-F foreign-private-issuer filing), then lists annual
  reports (40-F / 20-F / 10-K) from the submissions JSON API, returning the real
  primary-document URL on `www.sec.gov`.
  - **Auth**: No (SEC only asks for a descriptive `User-Agent`; a working
    default is baked in, `SEC_EDGAR_USER_AGENT` overrides it).
- **OpenCorporates** (already wired in `packages/_global`) — resilience fallback
  for name search when the federal source returns nothing.

## Coverage caveats

- The federal register covers only **federally incorporated** entities (~1/3 of
  Canadian companies). Provincial registries (ON / QC / BC / AB) are paid and
  out of MVP scope; the adapter falls back to OpenCorporates for those.
- Financials resolve only for issuers cross-listed in the US (their annual
  reports are filed with the SEC). Companies that file solely on **SEDAR+**
  return no filings — SEDAR+ is behind Radware/ShieldSquare bot protection with
  an undocumented POST search surface, so it is intentionally not used.
- Schedule I banks (e.g. RBC) are incorporated under the **Bank Act**, not the
  CBCA, so the CBCA register does not return the operating bank entity — look
  those up on EDGAR directly.

## Test companies

- Shopify Inc. — corpId `4261607`, BN `847871746`. Active, CBCA, cross-listed
  (NYSE: SHOP) → SEC 10-K filings. **Primary end-to-end test company.**
- Nutrien Ltd. — corpId `10263664`. Active, cross-listed (NYSE: NTR) → SEC 40-F
  filings.
- Open Text Corporation — corpId `4343506` (and successor entities). Cross-listed
  (NASDAQ: OTEX) → SEC 10-K filings.
- Bombardier Inc. / Bombardier Limitée — corpId `102784`. Federal; not
  US-cross-listed, so no EDGAR financials.

## Status

🟢 **Working** — federal name search, corp-number + Business-Number lookup, and
SEC-EDGAR annual-report metadata (with real downloadable document URLs) all
return live data key-free.

**Recommended next steps:**
1. Parse structured financials from the EDGAR filings (reuse the US adapter's
   XBRL companyfacts path) instead of returning metadata + document URL only.
2. Add a SEDAR+ path via FlareSolverr for TSX-only issuers not on US exchanges.
3. Add provincial adapters in priority order: ON (ServiceOntario), QC
   (Registraire des entreprises), BC (Corporate Online), AB (CORES).
