# Germany — NO FREE LIVE SOURCE (OffeneRegister.de API shut down)

## Status

🔴 **Disabled** (verified live 2026-07-20). All adapter methods raise
`AdapterNotImplementedError` (API returns `501 not_implemented`), after
validating identifier formats.

- **OffeneRegister.de** — the free JSON mirror this adapter was built on is
  gone: `https://offeneregister.de` is now a static GitHub Pages site that
  only offers the **bulk SQLite dump** for download; `/api/v1/companies`
  returns a GitHub Pages 404 HTML page, and the Datasette instance at
  `https://db.offeneregister.de/` answers **502 Bad Gateway**. The data
  snapshot was from 2019 anyway.
- **handelsregister.de** (official) — web-only, session-bound; filing
  documents cost €1 each. Out of scope per the MVP "no paid APIs" rule.
- **Bundesanzeiger** — the best-effort financials scrape resolved company
  names via OffeneRegister, so it was disabled with the rest.

`health_check` still probes `/api/v1/companies` once, and flips to
`degraded` with a "mirror restored" note if the API ever answers JSON again.

## Identifier

Formats are still validated so callers get actionable errors:

- Primary: `HRB` — accepted as plain digits (`42243`), prefixed
  (`HRB 42243` / `HRA 12345`), or with the Amtsgericht court name
  (`HRB 42243 München`).
- `COMPANY_NUMBER` — historical OffeneRegister slug.
- `VAT` — German USt-IdNr, format `DE` + 9 digits.

## Test companies (for whenever a source returns)

| Company | HRB | Court |
|---------|-----|-------|
| BMW AG | HRB 42243 | München |
| SAP SE | HRB 719915 | Mannheim |
| Volkswagen AG | HRB 100484 | Braunschweig |
| Siemens AG | HRB 6684 | München |

## Paths forward (free)

1. **GLEIF / OpenCorporates** via `packages/adapters/_global` — covers large
   German entities by LEI / mirrored registry data today.
2. **Ingest the OffeneRegister bulk SQLite dump** (several GB, 2019
   snapshot) behind a local lookup service — stale but free.
3. **Playwright-based handelsregister.de search** — the portal's *name
   search* is free (documents are not); needs the browser-pool
   infrastructure (`packages/adapters/_base/browser.py`) and careful
   session/rate handling.

## Skipped (paid) sources

- `handelsregister.de` documents — €1 per filing behind a session.
- Creditreform, Bisnode/Dun & Bradstreet, Bureau van Dijk, North Data — all
  paid, not in MVP scope.
