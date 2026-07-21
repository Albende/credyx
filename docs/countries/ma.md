# 🇲🇦 Morocco — GLEIF / AMF / OMPIC

## Identifier

- Primary: `LEI` (Legal Entity Identifier), 20-char alphanumeric. The only
  identifier resolvable through a free, key-less, worldwide-reachable API
  (GLEIF). Returned by `search_by_name`, consumed by
  `lookup_by_identifier` and `fetch_financials`.
- Secondary: `VAT` → ICE (Identifiant Commun de l'Entreprise), 15 digits.
  Issued since 2015, mandatory on every commercial document. Normalised
  by stripping whitespace, dashes, and an optional `MA` prefix. Not
  resolvable without paid OMPIC / DGI access.
- Secondary: `COMPANY_NUMBER` → RC (Registre du Commerce), e.g.
  `Casablanca 123456`. Not resolvable without paid OMPIC access; GLEIF
  exposes the bare RC number (`registeredAs`) as read-only metadata.

## Sources

- **GLEIF** (Global LEI Foundation) — https://api.gleif.org/api/v1.
  - Free, no key, reachable worldwide. Full-text search scoped to
    `filter[entity.legalAddress.country]=MA`; per-LEI record lookup.
  - Each record carries legal name, address, legal form, incorporation
    date, status and the RC number (`registeredAs`).
  - Coverage is partial (~200 Moroccan entities) and matches on the
    **legal** name, so a trade name that differs from the registered name
    (e.g. "Maroc Telecom" vs. its legal name "Itissalat Al-Maghrib")
    returns nothing — search by the legal name.
- **AMF regulated-information feed** — https://www.info-financiere.gouv.fr
  (dataset `flux-amf-new-prod`, Opendatasoft API v2).
  - Free, no key. The French Autorité des Marchés Financiers publishes
    every regulated filing of issuers admitted on Euronext Paris, indexed
    by LEI and ISIN, each with a directly-downloadable document URL
    (`url_de_recuperation`).
  - Moroccan issuers cross-listed on Euronext Paris (e.g. Maroc Telecom)
    file their audited annual reports / « documents d'enregistrement
    universel » here. `fetch_financials` selects the annual filings
    (`subtype_of_information` ∈ {Annual financial and audit reports,
    Registration document}).
- **OMPIC** (Office Marocain de la Propriété Industrielle et Commerciale)
  — https://www.ompic.ma/, https://www.directinfo.ma/. Full commercial
  register is paid; no free JSON API. **Blocked** — network-unreachable
  from outside MA and paywalled regardless.
- **DGI** (Direction Générale des Impôts) ICE validator —
  https://www.tax.gov.ma. HTML-only, CAPTCHA/session-gated, no stable
  public API.

## Test companies

- Maroc Telecom (Itissalat Al-Maghrib) — LEI `254900LH0G1ZIZ78Y462`,
  RC Rabat `48947`, ISIN `MA0000011488`, ticker `IAM`. Files annual
  reports via the AMF feed (cross-listed on Euronext Paris).
- OCP Group (OCP S.A.) — LEI `213800D26TAPVTCVWG40`, RC Casablanca
  `40327`. In GLEIF; no AMF filings (not on Euronext Paris) → financials
  return `[]`.
- Bank of Africa (ex-BMCE) — LEI `21380047DNBRQ54F9W43`, RC Casablanca
  `27129`.
- Attijariwafa Bank — **not in GLEIF** under an MA address (only European
  subsidiaries carry an LEI); not resolvable by this adapter today.

## Status

🟢 **OK** — `search_by_name` and `lookup_by_identifier` run live against
GLEIF (free, key-less); `fetch_financials` returns real, downloadable
annual reports for AMF-filing issuers.

**Capabilities**
- `search_by_name(name)` — GLEIF full-text, MA-scoped. Returns LEI-keyed
  matches with legal name, address, status and RC number. Legal-name
  match only (see coverage note above).
- `lookup_by_identifier(LEI, lei)` — GLEIF record → full `CompanyDetails`
  (name, legal form, incorporation date, address, RC).
- `lookup_by_identifier(VAT|COMPANY_NUMBER, …)` — raises
  `AdapterNotImplementedError`; ICE/RC resolution needs paid OMPIC/DGI
  access. Resolve by LEI instead.
- `fetch_financials(lei)` — AMF `flux-amf-new-prod` filtered by LEI,
  annual filings only, returned as `ANNUAL_REPORT` filings with a
  downloadable `document_url` (PDF or the URU ZIP package) and MAD
  currency. Non-filing / non-listed companies return `[]` (a factual
  "no public filings" answer, matching the FR convention). A 15-digit
  ICE also returns `[]` (not resolvable to filings without OMPIC).

**Known gaps / next steps**
- GLEIF only covers entities that hold an LEI. Broad name search over all
  Moroccan companies would need paid OMPIC access (Phase-2 decision,
  blocked by the no-paid-API MVP rule).
- The AMF feed only covers Euronext-Paris-admitted issuers. Domestic-only
  Casablanca-listed issuers publish on the (network-blocked)
  casablanca-bourse.com / AMMC and on their own IR portals; a future
  ingestion worker running from within MA could add those.
- The URU annual reports are ZIP packages; wiring the PDF/ZIP extraction
  pipeline would surface ratios for the listed cohort.
