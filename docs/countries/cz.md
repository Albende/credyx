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
  3. `GET /ias/ui/vypis-sl-detail?dokument={d}&subjektId={id}&spis={s}` → resolve
     the real download link `/ias/content/download?id=…`.
  - Documents are filed PDF or, for listed issuers, iXBRL/ESEF `.xhtml`. The
    download link truly returns that company's file (verified via
    `Content-Disposition`). Structured extraction (PDF/XBRL parsing) is a
    separate downstream step — the adapter returns per-filing metadata +
    document_url only.

## Test companies

- ČEZ a.s. (45274649); Škoda Auto (00177041); Komerční banka (45317054).

## Status

🟢 **Working** — search + lookup via ARES; filings (annual reports / financial
statements, last N years) via Sbírka listin (or.justice.cz), key-free.
