# 🇭🇷 Croatia — Sudski registar + FINA RGFI

## Identifiers

- **OIB** (Osobni identifikacijski broj) — 11 digits. Acts as both corporate
  tax ID and VAT base. Validated locally via ISO 7064 MOD 11,10.
  Maps to `IdentifierType.VAT` (carrier prefix `HR` when round-tripped).
- **MBS** (Matični broj subjekta) — court registration number, up to 9 digits.
  Maps to `IdentifierType.COMPANY_NUMBER`. Zero-padded to 9 digits.

## Sources

### Registry — Sudski registar (Croatian Court Registry)

- Public portal (HTML): https://sudreg.pravosudje.hr/registar/f?p=150
- **Open data JSON API**: https://sudreg-data.gov.hr/api/javni — free, but
  since the 2024 portal revamp it **requires OAuth2 client credentials**
  (the old anonymous `/subjekt_naziv` / `/subjekt_detalji` endpoints 404).
  - Register (free) at https://sudreg-data.gov.hr/ (APEX app "Registracija");
    you receive a Client Id / Client Secret by email.
  - Env vars consumed by the adapter: `HR_SUDREG_CLIENT_ID`,
    `HR_SUDREG_CLIENT_SECRET`. Without them every search/lookup raises a
    clear `AdapterError` and `health_check` reports `BLOCKED`.
  - Token: `POST /api/oauth/token` with HTTP basic auth and
    `grant_type=client_credentials`; `access_token` valid 6 h (21600 s).
  - `/javni/subjekti?tvrtka_naziv=...&only_active=false&offset=0&limit=n`
    — search by name.
  - `/javni/detalji_subjekta?tip_identifikatora={oib|mbs}&identifikator=...&expand_relations=true`
    — lookup.
  - Full OpenAPI catalog:
    https://sudreg-data.gov.hr/ords/SRN_OPEN_DATA/open-api-catalog/javni/
  - Developer guide (PDF): linked from the portal, "Upute za razvojne
    inženjere".
- **Rate limit**: 30 req/min (self-imposed, no documented hard limit).
- **ToS / robots.txt**: open government data; respectful crawler UA only.

### Financials — FINA RGFI (RETIRED)

- The anonymous public lookup `https://rgfi.fina.hr/IzvjestajiRGFI.action`
  now 404s; FINA's JavnaObjava-web replacement requires an interactive
  login. The sudreg open-data `/javni/gfi` endpoint exposes GFI document
  metadata only as bulk snapshots (no per-company query), so
  `fetch_financials` raises `AdapterNotImplementedError`. Currency was
  HRK ≤ 2022 and EUR from 2023-01-01 if a bulk-ingest pipeline is added
  later.

### VIES

- HR VAT lookup via SOAP at the EU VIES service is available for
  cross-border VAT validation; not yet wired here since OIB checksum
  validation + Sudski registar already covers identity confirmation.

## Test companies

- INA d.d. — OIB `27759560625`, MBS `080000604`
- HEP d.d. — OIB `28921978587`, MBS `080007911`
- Pliva Hrvatska d.o.o. — OIB `41538015885`
- Konzum plus d.o.o. — OIB `39963122365`

## Status

🟡 **KEY REQUIRED** (July 2026) — registry search + lookup are implemented
against the current OAuth2-protected `sudreg-data.gov.hr` API but need the
free `HR_SUDREG_CLIENT_ID` / `HR_SUDREG_CLIENT_SECRET` registration; the
adapter raises a clear `AdapterError` until the credentials are set.
`fetch_financials` raises `AdapterNotImplementedError` — FINA retired the
anonymous RGFI lookup and the open-data `/javni/gfi` endpoint is bulk-only.

**Field mappings are best-effort pending credentials**: response parsing
follows the documented v1 schema (`oib`, `mbs`, `skracena_tvrtka.ime`,
`tvrtka`, `sjediste.{ulica,kucni_broj,naziv_naselja}`,
`temeljni_kapitali`, `pretezite_djelatnosti`) with defensive fallbacks to
the legacy key names. Verify against a live token on first use.
