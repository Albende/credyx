# 🇬🇷 Greece — GEMI + VIES

## Identifiers

- **GEMI number** (`COMPANY_NUMBER`): General Commercial Registry,
  typically 9 digits (legacy records up to 12 digits accepted).
- **ΑΦΜ / VAT** (`VAT`): 9 digits. EU VAT prefix is `EL`, not `GR`.
  Validated with the standard checksum (weights 256/128/64/32/16/8/4/2
  over the first 8 digits, sum mod 11; mod 10 → 0).

## Sources

- **GEMI publicity portal** — https://publicity.businessportal.gr/
  - Search: `GET /api/companies?searchTerm={name}&page=1&pageSize={n}`
  - Detail: `GET /api/companies/{gemi}/details`
  - Free, no auth. Response shape may drift — adapter tolerates
    `items` / `companies` / `results` / `data` envelopes plus raw lists.
- **VIES** SOAP — https://ec.europa.eu/taxation_customs/vies/services/checkVatService
  - `countryCode=EL`, returns name + address for valid ΑΦΜ.
- **ATHEX** (listed companies only) — https://www.athexgroup.gr/web/guest/companies-financial-data
  - Free PDF annual reports. Index discovery is brittle JSP — not wired.

## Test companies

| Name | GEMI | ΑΦΜ |
|---|---|---|
| OPAP S.A. | 3823201000 | EL090027346 |
| Hellenic Telecommunications Organization (OTE) | 1037501000 | EL094019245 |
| National Bank of Greece | 6062511000 | EL094014201 |
| Coca-Cola HBC AG (Hellenic ops) | — | EL094277965 |

## Capabilities

| Capability | Status | Notes |
|---|---|---|
| `search_by_name` | ✅ | GEMI publicity portal (best-effort) |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | GEMI detail endpoint |
| `lookup_by_identifier(VAT)` | ✅ | VIES (`EL` prefix) |
| `fetch_financials` | ⚠️ | Returns `[]`; ATHEX index not yet wired |

- `requires_api_key = False`
- `rate_limit_per_minute = 30`

## Status

🟢 **Wired (MVP)**: name search + identifier lookup via GEMI publicity
portal and VIES. Financials are an explicit gap.

**Recommended next steps:**
1. Wire ATHEX listed-company annual report PDFs into `fetch_financials`
   once the PDF extraction pipeline lands.
2. Re-validate GEMI portal endpoints during the next adapter sweep — the
   JSON paths are undocumented and may shift.
3. Consider OpenSanctions enrichment for Greek shipping holdings (high
   sanctions-evasion risk profile).
