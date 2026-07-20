# 🇨🇿 Czech Republic — ARES

## Identifier

- Type: `ICO`
- Format: 8 digits. Example: 45274649 = ČEZ, a. s.

## Sources

- **Registry (search + lookup)**: https://ares.gov.cz/ — free public REST API,
  no auth. Soft ~60 req/min. Open data, allowed.
  - Search: `POST /ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat`
  - Lookup: `GET  /ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}`
- **Financials (filings)**: Sbírka listin on https://or.justice.cz/ — the public
  register's collection of documents, no auth, no bot wall (plain httpx). Flow:
  1. `GET /ias/ui/rejstrik-$firma?ico={ico}` → parse internal `subjektId`.
  2. `GET /ias/ui/vypis-sl-firma?subjektId={id}` → list of filed documents; rows
     tagged `účetní závěrka` (financial statements), `výroční zpráva` (annual
     report), each with the accounting year in `[YYYY]`.
  3. `GET /ias/ui/vypis-sl-detail?dokument={d}&subjektId={id}&spis={s}` → the
     stable, per-company detail page that resolves a `/ias/content/download?id=…`
     link. This detail URL is what the adapter returns as `source_url`.
  - Documents are filed PDF or, for listed issuers, iXBRL/ESEF `.xhtml`. The
    `download?id=…` token is bound to the session/backend node that minted it;
    behind or.justice.cz's round-robin a bare token URL only resolves ~half the
    time for a stateless caller, so the adapter does **not** emit it as
    `document_url`. Instead `source_url` points at the stable detail page — a
    downstream fetcher re-resolves a fresh download link there within its own
    session (verified: full re-resolve flow returns the real file with a
    `Content-Disposition` attachment, e.g. 30 MB ESEF `.xhtml` for ČEZ 2025).
    Structured extraction (PDF/XBRL parsing) is a separate downstream step —
    the adapter returns per-filing metadata (year, type, currency, period_end,
    format, source_url) only.

## Test companies

- ČEZ a.s. (45274649); Škoda Auto (00177041); Komerční banka (45317054).

## Status

🟢 **Working** — search + lookup via ARES; filings (annual reports / financial
statements, last N years) via Sbírka listin (or.justice.cz), key-free.
