# 🇸🇪 Sweden — VIES + Nasdaq Stockholm

## Identifier

- Primary: `COMPANY_NUMBER` — Organisationsnummer, 10 digits, printed `XXXXXX-XXXX`.
- Also: `VAT` — `SE` + 12 digits, where the first 10 digits are the Org Nr
  and the last two are always `01`.
- The 10th Org Nr digit is a Luhn (mod-10) check digit over the first 9.

## Sources

- **VIES** (https://ec.europa.eu/taxation_customs/vies/services/checkVatService)
  — EU VAT Information Exchange SOAP service. Free, no key, no contract.
  Validates a Swedish VAT and returns the registered name + address.
- **Nasdaq Stockholm**
  (https://www.nasdaq.com/market-activity/stocks) — free per-issuer
  financials pages for listed companies. Used for `fetch_financials`
  pointers; per-document URLs require scraper-pool work.
- **Bolagsverket Näringslivsregistret** (https://bolagsverket.se/) — the
  authoritative Swedish business register. The full-extract API is
  **paid by contract** and therefore not used in the free MVP (rule #2).
  The small open-data slice at `/ofr/` does not expose per-company
  lookup.
- **`allabolag.se` / `merinfo.se`** — deliberately *not* used; their ToS
  forbids automated scraping (rule #2 spirit).
- **SCB Företagsregister** (https://www.scb.se/oa/) — statistical
  aggregate data only, no per-company lookup.

**Auth**: None (VIES + Nasdaq).
**Rate limit**: 30 req/min adapter-side; VIES is unmetered but
intermittent.
**robots.txt / ToS**: VIES allows automated checks; Nasdaq.com permits
the per-issuer pages used here.

## Capabilities

| Operation | Status | Notes |
|-----------|--------|-------|
| `search_by_name` | ❌ Not implemented | No free authoritative name search. Bolagsverket is paid. |
| `lookup_by_identifier` (COMPANY_NUMBER) | ✅ | Via VIES (sends Org Nr + `01` as VAT). |
| `lookup_by_identifier` (VAT) | ✅ | Via VIES directly. |
| `fetch_financials` | ⚠️ Partial | Nasdaq Stockholm pointers for listed firms; `[]` otherwise. |
| `health_check` | ✅ | VIES probe against Volvo. |

## Test companies

| Company | Org Nr | VAT |
|---------|--------|-----|
| AB Volvo | 556012-5790 | SE556012579001 |
| Telefonaktiebolaget LM Ericsson | 556016-0680 | SE556016068001 |
| H&M Hennes & Mauritz AB | 556042-7220 | SE556042722001 |
| Spotify AB | 559026-0892 | — |

## Status

🟢 **Wired (VIES + Nasdaq for listed)** — paid Bolagsverket API and ToS-grey
aggregators (allabolag, merinfo) intentionally skipped per project rule #2.

**Recommended next step:** Once the scraper pool + ESEF XBRL parser land,
parse Nasdaq Stockholm issuer pages for per-year annual report PDFs and
extract structured financials from ESEF iXBRL filings (mandatory for EU
listed companies since 2021).
