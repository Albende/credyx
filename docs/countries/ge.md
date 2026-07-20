# 🇬🇪 Georgia — NAPR (National Agency of Public Registry)

## Identifier

- Types: `VAT`, `COMPANY_NUMBER`
- Format: **Identification Number** (საიდენტიფიკაციო ნომერი) — 9 digits.
  The same number serves as the corporate tax ID, the VAT registration
  ID, and the commercial registry primary key. Sometimes written with a
  `GE` prefix; the adapter strips it.

## Sources

- https://enreg.reestri.gov.ge/main.php — bilingual (ქართული / English)
  public business register operated by NAPR. The search form POSTs
  `c=search&m=find_legal_persons` and server-renders a result table
  (9-digit Identification Number, name, legal form, status). Used for
  both name search and ID lookup. **No browser and no captcha needed** —
  the plain POST is authoritative. The per-company `show_legal_person`
  detail page is now CAPTCHA-gated ("entered code does not match the
  image") and is deliberately not used.
- https://reportal.ge — the SARAS Reporting Portal (Service for
  Accounting, Reporting and Auditing Supervision). Key-free JSON/HTML
  endpoints:
  - `/en/Reports/GetProfileData?q=<id>` → JSON profile (registration
    date, registered address, phone, web, activity, directors) used to
    enrich the registry record captcha-free.
  - `/en/Reports/OrgReports?q=<id>` → company-specific list of reporting
    years that actually have filings.
  - `/en/Reports/OrgReportsByYear?q=<id>&year=<yyyy>` → per-year filing
    page whose public audit tab exposes the auditor firm + partner.
- https://rs.ge/ — Revenue Service VAT validator (partial public; not
  used by the adapter).
- https://gse.ge/ — Georgian Stock Exchange, limited free coverage of
  listed-issuer disclosures (not wired).
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min — no published budget.
- **robots.txt / ToS**: enreg.reestri.gov.ge and reportal.ge serve
  permissive robots policies; both are public-disclosure utilities. We
  send an identifiable User-Agent and keep volume polite.

## Test companies

Verified live present in NAPR + reportal (2026-07):

- Bank of Georgia JSC — `204378869` (reporter; NBG-regulated)
- TBC Bank JSC — `204854595` (reporter; NBG-regulated)
- Silknet JSC — `204566978` (reporter; non-financial)

Note: the previously listed `200032475` (Telasi) and `211302796`
(Wissol) no longer return a row from NAPR's `find_legal_persons` search
and were removed.

## Status

🟢 **Live — search + lookup + financial filing metadata.**

| Capability      | Status                                        |
|-----------------|-----------------------------------------------|
| Name search     | ✅ Live (NAPR find_legal_persons POST)        |
| ID lookup       | ✅ Live (NAPR + reportal profile enrichment)  |
| Financials      | ✅ Live filing metadata (reportal.ge)         |
| Health          | ✅ Probes Bank of Georgia via NAPR POST       |

## Limitations

- **Financial-statement PDFs are SMS-gated.** reportal.ge releases the
  actual statement document only after an SMS one-time-code flow
  (`RequestCode` → `DownloadReport`). `fetch_financials` therefore
  returns real per-company filing metadata — reporting `year`, `type`
  (`annual_report`), `currency` (GEL), the company-specific reportal
  `source_url`, and the audit-tab auditor firm/partner in
  `structured_data` — but never a `document_url`, because the document
  does not download key-free. No fabricated numbers.
- **reportal covers only mandatory reporters.** Category I–IV entities
  file there; a company absent from reportal returns `[]` from
  `fetch_financials` and simply loses the profile enrichment on lookup
  (NAPR name/form/status still resolve).
- **Search is Georgian-script.** NAPR's name field matches the
  registered Georgian (Mkhedruli) name; Latin/English queries generally
  return nothing. Callers with only a Latin name should resolve the
  9-digit ID first.
- **No separate company number.** Georgia uses a single 9-digit ID for
  tax and registry purposes, so both `VAT` and `COMPANY_NUMBER`
  identifier types resolve to the same number.
- **No capital figure.** The declared-capital field lived only on the
  now-captcha-gated NAPR detail page, so `capital_amount` stays `None`.

## Recommended next steps

1. Add a captcha/OCR or session path for the NAPR `show_legal_person`
   detail page to recover declared capital + full director roles.
2. Wire the reportal SMS one-time-code flow (or an authenticated SARAS
   account) so statement PDFs can be downloaded and parsed into
   structured financials.
3. Add a free name → ID fuzzy bridge (e.g. OpenCorporates GE tier) for
   Latin-name queries the Georgian-script NAPR search can't match.
