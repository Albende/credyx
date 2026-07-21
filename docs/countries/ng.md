# 🇳🇬 Nigeria — CAC iCRP / NGX

## Identifier

- Primary: `COMPANY_NUMBER` → RC number (Registration of Companies),
  issued by the Corporate Affairs Commission. Format is 1–10 digits,
  often presented with an `RC` prefix (e.g. `RC208767`). Normalised by
  stripping the prefix, spaces, and dashes. Note the CAC data still
  stores some legacy RCs with an embedded prefix/space (e.g. Nigerian
  Breweries is returned as `RC 613`); the adapter's comparison key strips
  those so a bare `613` still matches.
- Secondary: `VAT` → TIN (Tax Identification Number). No free public
  TIN→company resolver exists, so `lookup_by_identifier(VAT, tin)` raises
  `AdapterNotImplementedError`.

## Sources

- **CAC iCRP** (Corporate Affairs Commission, "CRP 3.0") —
  https://icrp.cac.gov.ng/public-search.
  - The public-search SPA is backed by an anonymous JSON API:
    `POST https://authapp.cac.gov.ng/name_similarity_app/api/public_search/search`
    with body `{"searchTerm": "...", "SearchType": "ALL"}`.
  - Returns, per company/business name: `approvedName`, `rcNumber`,
    `companyRegistrationDate`, `classificationName`, `natureOfBusiness`,
    `companyId`, and `status` (ACTIVE / INACTIVE / STRUCK OFF / ...).
  - **Auth**: none. No key, no cookie, no session token required.
  - **Rate limit**: not published; adapter throttles to 30 req/min.
  - Certified true copies / full statutory filings remain behind the paid
    CAC e-services portal (https://services.cac.gov.ng/) — out of scope.
- **NGX** (Nigerian Exchange) — corporate disclosures backend.
  - The disclosures table at
    https://ngxgroup.com/exchange/data/corporate-disclosures/ is served by
    a SharePoint OData list, `XFinancial_News`, exposed anonymously at
    `https://doclib.ngxgroup.com/_api/Web/Lists/GetByTitle('XFinancial_News')/items`.
  - Filtering `Type_of_Submission eq 'Financial Statements'` +
    `substringof('<issuer>',CompanyName)` yields the filed quarterly and
    audited annual financial statements for a listed issuer, each with a
    directly downloadable PDF on `doclib.ngxgroup.com`
    (`Content-Type: application/pdf`, no auth).
  - `fetch_financials` resolves the RC → approved name via CAC, then
    matches it against `CompanyName` here. Unlisted companies return `[]`.

## Test companies

- **Dangote Cement Plc** — RC `208767` (verified end-to-end: CAC returns
  `DANGOTE CEMENT PLC`, incorporated 1992-11-04; NGX has its audited annual
  + quarterly financial statements). NGX ticker `DANGCEM`.
- Nigerian Breweries Plc — CAC `rcNumber` is stored as `RC 613`; NGX
  ticker `NB`.
- MTN Nigeria Communications Plc — NGX ticker `MTNN` (financial statements
  present on NGX). Its current CAC RC differs from legacy listings; search
  by name via CAC to obtain the live RC.
- Zenith Bank Plc — NGX ticker `ZENITHBANK`.

> Note: the legacy RC numbers previously recorded here for MTN (`1241300`),
> Nigerian Breweries (`613` bare) and Zenith Bank (`150014`) no longer
> resolve to those entities in the new CAC iCRP dataset — resolve current
> RCs via `search_by_name`.

## Status

🟢 **OK** — CAC iCRP public JSON search powers real name search + RC
lookup with no API key; NGX `XFinancial_News` provides downloadable filed
financial statements for listed issuers.

**Capabilities**
- `search_by_name(query)` — `POST` to the CAC iCRP public-search API;
  returns live `CompanyMatch` rows (RC, approved name, status).
- `lookup_by_identifier(COMPANY_NUMBER, rc)` — searches CAC for the RC and
  returns a `CompanyDetails` (name, classification, status, incorporation
  date, nature of business) on exact RC match; `None` if not found.
- `lookup_by_identifier(VAT, tin)` — raises `AdapterNotImplementedError`
  (no free TIN→company resolver).
- `fetch_financials(rc)` — resolves the issuer name via CAC, then returns
  `FinancialFiling`s (year, type, NGN, downloadable PDF `document_url`)
  from NGX for listed issuers; `[]` for unlisted companies.

**Known gaps / next steps**
- Full statutory filings (annual returns, share allotments) stay behind
  paid CAC e-services — a Phase-2 decision.
- Quarterly NGX statements are typed `BALANCE_SHEET`; audited full-year
  ("AFS" / "Quarter 5") are typed `ANNUAL_REPORT`. Once the PDF
  text-extraction pipeline lands, these plug straight into the risk
  pipeline (same shape as UK PDFs).
- FIRS/JTB does not publish a documented free TIN API; once they ship one
  the `VAT` lookup path becomes a thin JSON client.
