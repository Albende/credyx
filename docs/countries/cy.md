# 🇨🇾 Cyprus — DRCOR + VIES

## Identifiers

- **HE Number** (Cyprus Company Number) — `HE` + up to 9 digits.
  Normalized internally as bare digits, zero-padded to 9 (DRCOR's own
  internal width). Mapped to `IdentifierType.COMPANY_NUMBER`.
- **VAT** — `CY` + 8 digits + 1 letter (e.g. `CY10000006V`). Mapped to
  `IdentifierType.VAT`.

## Sources

### DRCOR — Department of Registrar of Companies and Official Receiver

- Public free search:
  https://efiling.drcor.mcit.gov.cy/DrcorPublic/SearchForm.aspx
- Results:
  https://efiling.drcor.mcit.gov.cy/DrcorPublic/SearchResults.aspx
- Detail page:
  https://efiling.drcor.mcit.gov.cy/DrcorPublic/ViewOrganisation.aspx?id={internal_id}
- **Auth**: none for search and basic detail; structured filings sit
  behind a paid e-filing account and are intentionally NOT wired.
- **Mechanics**: ASP.NET WebForms. Each search round-trip needs
  `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, and `__EVENTVALIDATION` echoed
  from a prior GET. Adapter does this with httpx — no Playwright.
- **Rate limit**: throttled to 30 req / min adapter-side; DRCOR does not
  publish a public rate limit.
- **Robots / ToS**: search pages are publicly indexable; we set the
  shared respectful UA and back off on 429.

### VIES — EU VAT validation

- SOAP endpoint:
  https://ec.europa.eu/taxation_customs/vies/services/checkVatService
- Free, no key. Returns trader name + address when the member state
  exposes them (CY does).

### CySEC — for listed firms

- https://www.cysec.gov.cy/ — published filings are limited and
  per-issuer HTML/PDF; not yet wired.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | ✅ | DRCOR scrape (ASP.NET ViewState round-trip) |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | DRCOR scrape → ViewOrganisation |
| `lookup_by_identifier(VAT)` | ✅ | VIES SOAP |
| `fetch_financials` | ❌ | Returns `[]`; no free machine-readable source |
| `health_check` | ✅ | Probes DRCOR SearchForm for `__VIEWSTATE` |

## Test companies

- Bank of Cyprus Public Company Limited — `HE 165`
- Hellenic Bank Public Company Limited — `HE 6059`
- Cyprus Popular Bank Public Co Ltd — `HE 1`
- Cablenet Communication Systems Ltd — `HE 192919`

## Status

🟢 **Live**. DRCOR scrape + VIES VAT validation. Filings remain out of
scope until a free machine-readable source exists or paid DRCOR e-filing
is approved.
