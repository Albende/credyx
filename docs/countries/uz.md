# 🇺🇿 Uzbekistan — openinfo.uz (corporate disclosure portal)

## Identifier

- Type: `VAT` (primary), also accepted as `COMPANY_NUMBER`.
- Format: **INN** — 9 digits assigned by the State Tax Committee
  ("STIR" in Uzbek, "ИНН" in Russian). Sometimes written with a `UZ`
  prefix; the adapter strips it. Same number serves as the VAT
  registration ID and the corporate tax ID.

## Sources

- **https://openinfo.uz** — the Single Portal of Corporate Information
  run by the Center for Coordination and Development of the Securities
  Market. Official disclosure venue where Uzbek joint-stock companies,
  banks and insurers file annual reports and financial statements. Its
  backend `https://new-api.openinfo.uz` is an **unauthenticated Django
  REST API** and is the adapter's sole data source:
  - `GET /api/v2/organizations/organizations/?search=<name|inn>` —
    legal-entity search returning INN, names, address, OKED/OKONX,
    director, ticker, listing status, website, email.
  - `GET /api/v2/organizations/organizations/{id}/` — full org record.
  - `GET /api/v2/reports/{jsc,bank,insurance}/annual/?search=<inn>` —
    filed annual reports for that entity.
  - `GET /api/v2/reports/{cat}/annual/{id}/` — report detail carrying the
    actual filed balance-sheet and financial-results line items plus the
    auditor's conclusion PDF (`/media/audit_conclusion/*.pdf`).
- Public entity page: `https://openinfo.uz/en/organizations/{id}`.
- Public report page: `https://openinfo.uz/en/reports/{cat}/{id}`.
- **Auth**: None. No API key.
- **Rate limit**: Self-imposed at 30 req/min — the portal publishes no
  budget.

## Test companies

| Company | INN (STIR) | openinfo org id | Type |
|---------|-----------|-----------------|------|
| Hamkorbank ATB (listed, HMKB) | `200242936` | 8 | bank |
| Kapitalbank ATB | `207127843` | — | bank |
| Uzbekistan Airways AJ | `306628114` | — | jsc |

## Status

🟢 **Live — search, lookup and financials all return real data.**

| Capability  | Status                                              |
|-------------|-----------------------------------------------------|
| Name search | ✅ openinfo.uz organizations search                 |
| INN lookup  | ✅ openinfo.uz org record (INN, director, OKED, …)  |
| Financials  | ✅ Filed annual reports — real balance-sheet /       |
|             |    financial-results line items + audit PDF (UZS)   |
| Health      | ✅ Probes `new-api.openinfo.uz/api/v2/reports/`     |

`fetch_financials` returns one `FinancialFiling` per disclosed year
(newest first), each with:

- `year` / `period_end` from the report's `reporting_year`,
- `currency = "UZS"`,
- `structured_data` = the filed `balance_sheet`, `financial_results` and
  `activity_ratios` line items exactly as disclosed (never fabricated),
- `document_url` = the auditor's conclusion PDF (percent-encoded, verified
  downloadable) **only when one is filed**, else `None`,
- `source_url` = the public openinfo.uz report page.

## Limitations

- **Coverage = disclosing entities.** openinfo.uz holds listed issuers,
  JSCs, banks and insurers that publicly disclose — a few thousand
  entities, not the full ~350k-company registry. A private SME with no
  disclosure obligation will not be found. `search_by_name` and
  `lookup_by_identifier` return `[]` / `None` for such companies rather
  than fabricating a record.
- **Report units.** Balance-sheet / P&L values are stored as filed
  (thousand UZS for most JSCs). The risk engine should treat `currency`
  as `UZS` and not assume a scale beyond what the filing states.

## Recommended next steps

1. **Broad registry bridge (stat.uz / orginfo.uz).** The full legal-entity
   registry is exposed as HTML at `orginfo.uz` (mirrors stat.uz), with a
   clean per-org JSON-LD block (`taxID`, address, `foundingDate`, status).
   Wiring it as a fallback for `search_by_name` / `lookup_by_identifier`
   would extend coverage from disclosing entities to all ~350k companies.
2. **PDF extraction.** Pipe the audit-conclusion / IFRS (`int_report`,
   `msfo`) PDFs through the Celery `pypdf` worker so their text reaches the
   LLM via `pdf_text_excerpts`.
3. **Quarterly reports.** `reports/{cat}/quarter/` mirror the annual
   structure and could feed a more current view between annual filings.
