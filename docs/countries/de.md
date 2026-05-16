# Germany — Handelsregister via OffeneRegister.de + Bundesanzeiger

## Identifier

- Primary: `HRB` (Handelsregister B number) — e.g. `HRB 42243` plus the
  Amtsgericht (registering court) name, e.g. `HRB 42243 München`.
- Alternates accepted by the adapter:
  - `COMPANY_NUMBER` — OffeneRegister.de slug (stable, URL-safe id).
  - `VAT` — German USt-IdNr, format `DE` + 9 digits.

## Sources

### OffeneRegister.de — registry (FREE, JSON)

- Base: `https://offeneregister.de`
- Search: `GET /api/v1/companies?name={query}&size={n}`
- Detail: `GET /api/v1/company/{slug}`
- Auth: none.
- Rate limit: be polite; the adapter is configured at 30 req/min.
- robots.txt / ToS: permitted, the project is explicitly an open mirror of
  the Handelsregister.

### Bundesanzeiger — financial filings (FREE, HTML)

- Base: `https://www.bundesanzeiger.de`
- Public search: `https://www.bundesanzeiger.de/pub/en/start?globalsearch_keyword={name}`
- No JSON API — adapter does a best-effort HTML scrape of result rows for
  links labelled "Jahresabschluss" / "annual report" / "Konzernabschluss"
  paired with a 4-digit year.
- If the page structure changes, `fetch_financials` returns `[]` rather
  than crashing.

## Skipped (paid) sources

- `handelsregister.de` bulk download — €1 per filing document behind a
  session. Per the MVP rule against paid commercial APIs, not used.
- Creditreform, Bisnode, Bureau van Dijk — all paid, not in scope.

## Test companies (real)

| Company | HRB | Court |
|---------|-----|-------|
| BMW AG | HRB 42243 | München |
| SAP SE | HRB 719915 | Mannheim |
| Volkswagen AG | HRB 100484 | Braunschweig |
| Siemens AG | HRB 6684 | München |

Integration tests in `packages/adapters/de/tests/test_de.py` hit the live
OffeneRegister API against these companies.

## Status

- Registry lookups (search by name, lookup by HRB or slug): LIVE
- Financial filings (Bundesanzeiger annual reports): BEST-EFFORT scrape,
  returns `[]` on structural change. PDF text extraction not yet wired in
  — once the cross-cutting PDF pipeline lands (`pypdf` in a Celery worker)
  the URLs we surface here become directly consumable by `LLMService`.

## Known limitations

- OffeneRegister has no VAT lookup endpoint — `IdentifierType.VAT`
  resolution is a fallback name-search and may miss companies that don't
  publish the USt-IdNr in their registry entry.
- Director and shareholder data are not consistently exposed by the public
  OffeneRegister payload, so `CompanyDetails.directors` / `shareholders`
  are intentionally left empty (better empty than fabricated).
- Bundesanzeiger filings often link to publication pages rather than raw
  XBRL/PDF; the consumer must follow the `document_url` to retrieve the
  underlying document. ESEF XBRL extraction is on the cross-cutting infra
  roadmap.
