# 🇸🇮 Slovenia — AJPES

## Identifiers

- **Matična številka** (Registration Number) — primary, 10 digits.
  Mapped to `IdentifierType.COMPANY_NUMBER`.
- **Davčna številka** (Tax / VAT number) — `SI` + 8 digits.
  Mapped to `IdentifierType.VAT`. Both forms (with or without the `SI`
  prefix) are accepted on input; normalized output is `SI` + 8 digits.

## Sources

- **AJPES eObjave** — court-register publications.
  https://www.ajpes.si/eObjave/
  Public, no auth. Result rows expose: date, type, company name, matična,
  davčna, Srg number. Used as the canonical identifier-pair source.
- **AJPES JOLP** — public list of annual-report filers.
  https://www.ajpes.si/jolp/
  Public, no auth. Result rows expose: name, street, postcode, city,
  district court, file number. Used to enrich `registered_address`. The JOLP
  *company detail* page (`podjetje.asp`) with the actual figures is gated
  behind the free-but-registered AJPES login, so it is **not** the financials
  source.
- **Ljubljana Stock Exchange — SEOnet** — official disclosure portal.
  https://seonet.ljse.si/
  Public, no auth. Listed issuers file audited annual reports and
  semi-annual/interim reports here, mostly as ESEF (iXBRL) packages plus
  PDFs. Flow used by `fetch_financials`:
  1. Resolve the AJPES company name from the matična (eObjave).
  2. Match it against the SEOnet brand-first issuer directory
     (`fast_search_issuer` select on `default_en.aspx`). Match requires equal
     leading brand token **and** one name's significant tokens ⊆ the other's,
     so an unrelated firm sharing a generic lead word cannot bind.
  3. POST `default_en.aspx` with `doc=ANNUAL_AND_SEMI_ANNUAL_REPORTS`,
     `fast_search_issuer=<id>`, `field.selected_year=<Y>` — returns that
     issuer's reports filed in year Y.
  4. Follow each announcement (`?doc_id=<N>`) to its attachment
     (`file.aspx?AttachmentID=<A>`); the `document_url` is emitted only after
     the byte stream returns HTTP 200, and `document_format` (pdf / xbrl) +
     `period_end` come from the ESEF `<LEI>-YYYY-MM-DD-…zip` filename.
  Registry matičnas carry **no** SEOnet cross-walk, so the name match is the
  only bridge; private (non-listed) companies raise
  `AdapterNotImplementedError` — their accounts are AJPES-login-only.
- **Auth**: None for any endpoint used above.
- **Rate limit**: Not formally documented. Adapter throttles to
  30 req/min as a respectful default.
- **robots.txt**: AJPES `/robots.txt` only disallows `MJ12bot` from `/fipo/`;
  SEOnet `/robots.txt` imposes no relevant restriction on the public
  disclosure views.

## Test companies

| Company | Matična | Davčna (VAT) | SEOnet issuer | Financials |
|---|---|---|---|---|
| KRKA, tovarna zdravil, d. d., Novo mesto | 5043611000 | SI82646716 | 434 | ✅ listed |
| Petrol, d. d., Ljubljana | 5025796000 | SI80267432 | 487 | ✅ listed |
| Poslovni sistem Mercator, d. d. | 5300231000 | SI45884595 | — | delisted → 501 |
| Gorenje, d. o. o. | 5163676000 | — | 389 | listed (few reports) |

Note: 5043591000 (sometimes circulated as Krka's matična) is a typo —
the registry returns the company under 504361**1**000.

## Status

🟢 **Live** — registry data and listed-company financials both live.

- `search_by_name`: ✅ via eObjave `Firma=` (returns name + matična + VAT).
- `lookup_by_identifier`: ✅ via eObjave `Maticna=` / `Davcna=`, address
  enriched from JOLP.
- `fetch_financials`: ✅ for Ljubljana Stock Exchange (SEOnet) issuers —
  returns real annual/semi-annual report filings with a verified downloadable
  `document_url` (ESEF iXBRL zip or PDF), `period_end`, and `EUR` currency.
  Non-listed (private) companies raise `AdapterNotImplementedError` because
  their filed accounts are only available behind the AJPES registered
  session. No API key required for any of this.
- `health_check`: probes `eObjave/default.asp?s=48`; capabilities now report
  `financials: True`.

## Known limitations

- No directors, share capital, or NACE codes from public endpoints.
- Financials cover **listed** issuers only. Private-company accounts remain
  behind the free-but-registered AJPES session (a browser pool + credentials,
  Phase 2).
- SEOnet issuer resolution is by name (no matična cross-walk exists). The
  match is deliberately strict (equal brand token + subset of significant
  tokens); a company whose AJPES name diverges strongly from its exchange
  name may fall through to a 501 rather than risk a wrong-company match.
- `fetch_financials` returns filing **metadata + document URL**, not parsed
  figures. Extracting the numbers from the ESEF/PDF documents (feeding
  `structured_data`) is the follow-on step — the ESEF parser at
  `packages/risk/xbrl_esef.py` is the intended consumer.
- HTML scrape — if AJPES or SEOnet restructures result tables, parsing will
  degrade to empty lists (defensive parsing already in place; tests are
  integration-marked to catch real-world regressions).

## Recommended next step

1. Parse the downloaded ESEF iXBRL packages into `structured_data` via the
   shared `packages/risk/xbrl_esef.py` parser (KRKA/Petrol file full ESEF).
2. For PDF-only interim reports, wire `pypdf` text extraction in a Celery
   worker and pass excerpts to the LLM.
3. (Optional) Open a free AJPES account + cookie-jar session to reach the
   JOLP `podjetje.asp` figures for **private** companies.
