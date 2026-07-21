# 🇧🇦 Bosnia and Herzegovina — Banja Luka Stock Exchange (BLSE)

## Identifier

- Type: `COMPANY_NUMBER` — the BLSE issuer code (exchange ticker), e.g. `TLKM`
  = Telekom Srpske a.d. Banja Luka.
- BiH has no single national company number usable over a free API. JIB
  (13-digit tax ID) and MB (registration number) exist but are only queryable
  through the paid/stateful court registries (see below), so the adapter keys
  on the exchange code, which round-trips cleanly through all three methods.

## Why not the court registries

BiH incorporation records are split across three systems, none free +
machine-readable:

- **FBiH** — `bizreg.pravosudje.ba` is now a stateful Oracle APEX app
  (`/pls/apex/f?p=183`); no JSON API, session-bound form posts only.
- **Republika Srpska** — the old `bizreg.esrpska.com` host is offline (no DNS).
- **Brčko District** — `bizreg.osbd.ba`, separate portal, web-only.

The previous adapter posted guessed `/pretraga/subjekti` / `/subjekt?jib=`
endpoints that 404 — they never existed. Replaced with a live, verified source.

## Sources (free, no auth, no bot wall — plain httpx)

Base: `https://www.blberza.com`

- **Search (name)**:
  `GET /Code/Services/Autocompleter/IssuerListAutocompleterService.ashx?q={name}`
  → JSON `[[code, name], …]`. Real substring search over BLSE issuers.
- **Lookup (by issuer code)**:
  `GET /Pages/IssuerData.aspx?code={code}` → HTML issuer profile. Parsed:
  legal name (`<h1>`), address, phone, web, email, security code
  (`Emisije emitenata`), activity (`Područje djelatnosti`), and the ten
  largest shareholders with percentages.
- **Financials (filings)**:
  `GET /Pages/FinancialReports.aspx?code={code}` → the issuer's own financial
  page. The `ddlGodisnji` `<select>` lists the years with filed annual reports;
  the "Skraćeni bilans stanja" table carries the real APIF-sourced unaudited
  abbreviated balance sheet for the two most recent years (fixed/current assets,
  cash, total assets, equity, share capital, reserves, retained earnings,
  non-current/current liabilities). The adapter returns one `FinancialFiling`
  per available year (currency BAM, `source_url` = the issuer's reports page)
  and embeds the parsed balance-sheet totals in `structured_data` for the years
  the summary table covers. No `document_url` — the per-statement views are
  ASP.NET postbacks with no stable direct-download URL. Numbers are scraped
  from the company's own page, never synthesized.

## Coverage & limits

- Covers Republika Srpska capital-market issuers (RS listed / registered
  companies). FBiH-only private companies are not reachable via any free API
  and return empty results (never mock data).
- Companies with no filed statements (e.g. small dormant issuers) return `[]`
  from `fetch_financials`.

## Test companies

- **Telekom Srpske a.d. Banja Luka** — code `TLKM` (search "telekom"; lookup
  returns shareholders incl. Telekom Srbija 65.0%; financials return real
  balance sheets, 2025 total assets ≈ 1.72 bn BAM).
- Bosna FO a.d. Banja Luka — code `BSNA` (search "bosna"; lookup works;
  no filed financials → `[]`).

## Status

🟢 **Working** — search + lookup + financials all return real live data via
BLSE (blberza.com), key-free, no bot wall.
