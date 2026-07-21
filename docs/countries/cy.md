# 🇨🇾 Cyprus — DRCOR + GLEIF/ESEF + VIES

## Identifiers

- **HE Number** (Cyprus Company Number) — `HE` + up to 9 digits.
  Normalized internally as bare digits, zero-padded to 9 (DRCOR's own
  internal width). Mapped to `IdentifierType.COMPANY_NUMBER`.
- **VAT** — `CY` + 8 digits + 1 letter (e.g. `CY10000006V`). Mapped to
  `IdentifierType.VAT`.

## Sources

### DRCOR — Department of Registrar of Companies and Intellectual Property

- Public free results (plain GET, no auth, no JS):
  `https://efiling.drcor.mcit.gov.cy/DrcorPublic/SearchResults.aspx?name={name}&number={num}&searchtype=optStartMatch&index=1&tname=%25&sc=0`
- **Auth**: none for search. The old ASP.NET `SearchForm.aspx` postback
  simply 302-redirects to the `SearchResults.aspx` query-string URL above,
  so the adapter skips the ViewState round-trip and GETs the results page
  directly.
- **Results shape**: an ASP.NET GridView. Each `tr.basket` row carries
  `Name | TypeCode (ΗΕ=company / ΕΕ=business name) | Registration Number |
  Type | Name Status | Organisation Status`. Company names are stored in
  Latin (or, for some issuers, their registered Greek legal name). Status
  and type labels are Greek and mapped to English adapter-side
  (accent-insensitive).
- **Per-company detail page**: the row `Select` button is a session-bound
  `__doPostBack` that the public endpoint rejects (`Error.aspx?code=d1`),
  so `ViewOrganisation.aspx` is not reachable statelessly. All fields come
  from the row; the number-scoped `SearchResults` URL is used as the
  company's stable public `source_url`.
- **Number vs business-name collision**: the ΗΕ (company) and ΕΕ
  (business-name) registers share a number space, so HE lookup filters to
  the ΗΕ type code. Multiple name rows per number are collapsed keeping the
  current name (`Τελευταίο Όνομα`); superseded names are surfaced in
  `raw["previous_names"]`.
- **Rate limit**: throttled to 30 req / min adapter-side.

### GLEIF + filings.xbrl.org — ESEF financial filings (free, no key)

- **HE → LEI**: GLEIF JSON:API, `filter[entity.registeredAs]={digits}` +
  `filter[entity.legalAddress.country]=CY`. The numeric part of the
  returned `registeredAs` (e.g. `ΗΕ 28390`) is verified against the HE
  number. `https://api.gleif.org/api/v1/lei-records`
- **LEI → filings**: `https://filings.xbrl.org/api/filings?filter[entity.identifier]={LEI}&sort=-period_end`.
  Each filing yields the ESEF iXBRL report package (`package_url`, a real
  downloadable `.zip`), used as `FinancialFiling.document_url`
  (`document_format="xbrl"`), plus the human viewer as `source_url`.
- Covers Cyprus-domiciled listed issuers filing under the EU ESEF mandate
  (2021+). Companies whose only ESEF filer is a foreign-domiciled parent
  (e.g. Bank of Cyprus Holdings, IE) return `[]` for the CY operating
  entity — no fabrication.

### VIES — EU VAT validation

- SOAP endpoint:
  `https://ec.europa.eu/taxation_customs/vies/services/checkVatService`
- Free, no key. Returns trader name + address when CY exposes them.

## Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `search_by_name` | ✅ | DRCOR public GET → GridView parse |
| `lookup_by_identifier(COMPANY_NUMBER)` | ✅ | DRCOR GET, ΗΕ-filtered, current-name |
| `lookup_by_identifier(VAT)` | ✅ | VIES SOAP |
| `fetch_financials` | ✅ | GLEIF `registeredAs` → LEI → filings.xbrl.org ESEF packages |
| `health_check` | ✅ | Probes DRCOR results for `GridView1` |

## Test companies

- **Logicom Public Limited — `HE 28390`** (LEI `549300IPBYXB0HYPIC28`)
  — search + lookup + 1 ESEF annual report (2021).
- **Vassiliko Cement Works Public Company Limited — `HE 1210`**
  (LEI `213800BYCUHXLRDEA130`) — lookup + 2 ESEF annual reports
  (2022, 2021).
- Bank of Cyprus Public Company Limited — `HE 165` — search + lookup work;
  `fetch_financials` returns `[]` (the ESEF filer is the IE parent, Bank of
  Cyprus Holdings).

## Status

🟢 **Live**. DRCOR public GET for name/HE search and lookup; VIES for VAT;
ESEF filings via GLEIF → filings.xbrl.org (free, no API key). DRCOR's own
paywalled e-filings are never used.
