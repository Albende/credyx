# 🇵🇱 Poland — KRS + Biała Lista

## Identifiers

- `KRS` — 10-digit court registry number (primary)
- `NIP` — 10-digit tax id; same number used as the Polish VAT (with a `PL`
  prefix). Treated as both `NIP` and `VAT` in `IdentifierType`.
- `REGON` — 9 or 14-digit statistical id (lookup not implemented; needs the
  GUS BIR API which requires a manually-approved free key).

## Sources

| Purpose | Endpoint | Auth | Notes |
|---------|----------|------|-------|
| Full registry record | `GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json` | none | Falls back to `rejestr=S` (associations) on 404 |
| Filing mentions | `GET https://api-krs.ms.gov.pl/api/krs/OdpisPelny/{krs}?rejestr=P&format=json` | none | `dzial3.wzmiankiOZlozonychDokumentach` records every annual-statement filing (period, submission date, entry id) |
| NIP → KRS / VAT status | `GET https://wl-api.mf.gov.pl/api/search/nip/{nip}?date=YYYY-MM-DD` | none | `date` parameter is required |
| Name → KRS | `GET https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={name}&filter[entity.legalAddress.country]=PL` | none | Polish LEI records carry KRS in `entity.registeredAs` under authority `RA000484`. LEI-registered entities only |
| Filing PDF | `GET https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Search?krs={krs}&signatureType=B&...` → `Monitor/Download?id={id}` | none | MSiG search is **not** behind Incapsula; RDF-signature (`[RDF/…]`) rows are the financial filings; `Download` serves the real gazette PDF |
| Name search (web) | `https://wyszukiwarka-krs.ms.gov.pl/` | none | **Blocked** — Incapsula, session-based (GLEIF used instead) |
| Filings (RDF portal) | `https://ekrs.ms.gov.pl/rdf/pd/search_df?nr_krs={krs}` | none | **Blocked** by Incapsula; kept as human `source_url` deep-link only |

- **Rate limit**: KRS REST tolerates ~60 req/min in practice; adapter caps
  at the same. Biała Lista API is generous and we hit it at most once per
  lookup.
- **robots.txt / ToS**: All three Ministry sources are open data — allowed.

## Test companies (used by integration tests)

| Name | KRS | NIP |
|------|-----|-----|
| PKN Orlen S.A. (now ORLEN S.A.) | `0000028860` | `7740001454` |
| KGHM Polska Miedź S.A. | `0000023302` | `6920000013` |
| CD Projekt S.A. | `0000006865` | `7342867148` |
| Allegro.eu S.A. | `0000635012` | — |

## Capabilities

| Capability | Status |
|-----------|--------|
| `lookup_by_identifier` (KRS, NIP, VAT) | ✅ Live |
| `lookup_by_identifier` (REGON) | 🚫 Not implemented — GUS BIR key needed |
| `search_by_name` | ✅ Live via GLEIF (LEI-registered entities → KRS) |
| `fetch_financials` | ✅ Live — filing metadata from OdpisPelny + downloadable MSiG gazette PDFs |

## Known limitations

- **Name search covers LEI-registered entities only.** The official KRS
  web search at `wyszukiwarka-krs.ms.gov.pl` is behind Incapsula and needs
  a full browser session, so it is not a reliable request-path source.
  Instead the adapter resolves names through GLEIF's public JSON:API:
  Polish LEI records carry their KRS in `entity.registeredAs` under
  registration authority `RA000484`, so a name hit resolves straight to a
  KRS. This means SMEs without an LEI won't surface in name search —
  lookup by KRS / NIP still works for them.
- **Financials are filing metadata + the official gazette PDF, not parsed
  numbers.** `OdpisPelny` lists every annual-statement filing (fiscal
  period, submission date, entry id). The statement files themselves live
  in the Incapsula-walled RDF portal, but the same filings are announced in
  MSiG (Monitor Sądowy i Gospodarczy), whose search API is open. RDF-signature
  announcements (`[RDF/…]`) are the financial filings; `Monitor/Download?id=`
  serves the real gazette-issue PDF, attached as `document_url`. Parsing the
  statement line-items (iXBRL) is still future work.
- **PESEL / surnames are masked** by the KRS API itself (e.g. Director
  `"nazwiskoICzlon": "N**********"`). This is by design and not an
  adapter issue. The `directors` list will contain partial names from
  KRS — credit decisions should rely on the company-level data, not on
  individual identification.

## Status

🟢 **LIVE** — all three capabilities work against production endpoints,
key-free: lookup by KRS / NIP / VAT (KRS REST + Biała Lista), name search
via GLEIF (→ KRS), and `fetch_financials` returning filing metadata from
OdpisPelny plus downloadable MSiG gazette PDFs.

**Next steps:** parse the MSiG / RDF PDFs into structured line-items
(iXBRL) so the risk engine gets real balance-sheet numbers; add GUS BIR key
for REGON lookup and non-LEI SME name search.
