# 🇵🇱 Poland — KRS (companies) + CEIDG / Biała Lista (sole traders)

Poland splits its business register in two, and a credit platform has to
cover both:

- **KRS** (Krajowy Rejestr Sądowy) — **companies / spółki** (sp. z o.o.,
  S.A., etc.). Free JSON REST.
- **CEIDG** (Centralna Ewidencja i Informacja o Działalności Gospodarczej) —
  **sole proprietorships** (*jednoosobowa działalność gospodarcza* / JDG).
  These are **not** in KRS. Most Polish businesses by count are JDG. The
  authoritative, free, name-searchable source is the CEIDG v3 REST
  warehouse; it needs a free JWT (see [Environment variables](#environment-variables)).

The adapter resolves **any** Polish business — company or sole trader —
through a layered set of free sources.

## Identifiers

- `KRS` — 10-digit court registry number (companies only).
- `NIP` — 10-digit tax id; same number used as the Polish VAT (with a `PL`
  prefix). Treated as both `NIP` and `VAT`. **Every** Polish business has one.
- `REGON` — 9 or 14-digit statistical id. Now resolved **key-free** via
  Biała Lista (8-digit inputs are left-padded to the canonical 9 digits).

## Sources

| Purpose | Endpoint | Auth | Notes |
|---------|----------|------|-------|
| Company registry record | `GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json` | none | Falls back to `rejestr=S` (associations) on 404 |
| Company filing mentions | `GET https://api-krs.ms.gov.pl/api/krs/OdpisPelny/{krs}?rejestr=P&format=json` | none | `dzial3.wzmiankiOZlozonychDokumentach` records every annual-statement filing |
| **Sole trader / company by NIP** | `GET https://wl-api.mf.gov.pl/api/search/nip/{nip}?date=YYYY-MM-DD` | none | Returns the subject: company → `krs`; sole trader → real identity (name, REGON, address, registration date, VAT status, bank accounts) with `krs=null` |
| **Sole trader / company by REGON** | `GET https://wl-api.mf.gov.pl/api/search/regon/{regon}?date=YYYY-MM-DD` | none | Same subject shape as the NIP endpoint; REGON must be the 9-digit (leading-zero) or 14-digit form |
| **Sole trader NAME search** | `GET https://dane.biznes.gov.pl/api/ceidg/v3/firmy?nazwa={name}&limit={n}` | **Bearer JWT** (`PL_CEIDG_TOKEN`) | The only free source that indexes CEIDG/JDG by name. Also covers companies. `firmy[]` → `{id, nazwa, status, dataRozpoczecia, wlasciciel:{imie,nazwisko,nip,regon}, adresDzialalnosci{…}, link}` |
| **Sole trader detail** | `GET https://dane.biznes.gov.pl/api/ceidg/v3/firma?nip={nip}` (or `?regon=`, `/firma/{id}`) | **Bearer JWT** | Full trade name, `pkd[]`/`pkdGlowny` (PKD/NACE), `telefon`/`email`/`www`, dates, status. Used to enrich Biała-Lista sole-trader records |
| Company name → KRS | `GET https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={name}&filter[entity.legalAddress.country]=PL` | none | Polish LEI records carry KRS in `entity.registeredAs` under authority `RA000484`. LEI-registered companies only |
| Company filing PDF | `GET https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Search?krs={krs}&signatureType=B&…` → `Monitor/Download?id={id}` | none | MSiG search is **not** behind Incapsula; RDF-signature (`[RDF/…]`) rows are the financial filings; `Download` serves the real gazette PDF |
| Company name search (web) | `https://wyszukiwarka-krs.ms.gov.pl/` | — | **Blocked** — Incapsula, session-based (GLEIF used instead) |
| CEIDG public web search | `https://aplikacja.ceidg.gov.pl/CEIDG/CEIDG.Public.UI/Search.aspx` | — | **Dead end for automation** — ASP.NET WebForms + **CAPTCHA** (`hfNewCaptchaVal`) + 403 to bots. The v3 REST API is the machine path |

- **CEIDG rate limit**: the v3 warehouse enforces a minimum gap between
  requests (~3.6 s optimal) with a **180 s lockout** if violated. The
  adapter fires at most one CEIDG request per public call; do not batch.
- **Other rate limits**: KRS REST and Biała Lista tolerate ~60 req/min; the
  adapter caps there.
- **robots.txt / ToS**: KRS, CEIDG, Biała Lista and MSiG are all official
  open-government data — allowed.

## Environment variables

| Var | Required? | Purpose |
|-----|-----------|---------|
| `PL_CEIDG_TOKEN` (alias `PL_CEIDG_JWT`) | Optional but recommended | Bearer JWT for CEIDG v3. **Without it**: company lookup/search and sole-trader lookup **by NIP/REGON** still work key-free (Biała Lista). **With it**: sole-trader **name** search turns on, and sole-trader records gain the full trade name, PKD codes and contacts. A missing token is skipped silently in name search; an **invalid** token raises a clear `AdapterError`. |

### How to get `PL_CEIDG_TOKEN` (free)

The CEIDG "Hurtownia Danych" API key is free but issued only to a party with
a Polish **Profil Zaufany** or **mObywatel** identity (the operator, not the
end user):

1. Go to **`https://biznes.gov.pl/pl/e-uslugi/00_9999_00`** ("Wniosek o
   dostęp do raportów CEIDG i Biznes.gov.pl / Hurtownia Danych").
2. Log in with **Profil Zaufany** or the **mObywatel** app.
3. Fill in the access request (select the firm / personal use, contact
   fields), accept the terms.
4. Sign it with **Podpis Zaufany** or a qualified signature.
5. Within minutes an email arrives with the **API key** — that string is the
   JWT. Set it as `PL_CEIDG_TOKEN` (used verbatim as `Authorization: Bearer
   {token}`).

Endpoints: production `https://dane.biznes.gov.pl/api/ceidg/v3`, test
`https://test-dane.biznes.gov.pl/api/ceidg/v3`.

## Test companies (used by integration tests)

| Name | Type | KRS | NIP | REGON |
|------|------|-----|-----|-------|
| ORLEN S.A. | Company (KRS) | `0000028860` | `7740001454` | — |
| KGHM Polska Miedź S.A. | Company (KRS) | `0000023302` | `6920000013` | — |
| CD Projekt S.A. | Company (KRS) | `0000006865` | `7342867148` | — |
| **AKTIV JUSTYNA OSIP** | **Sole trader (CEIDG/JDG)** | — (not in KRS) | `6121719035` | `021405924` |

`AKTIV JUSTYNA OSIP` (Bolesławiec, registered 2010-12-01) is the reference
sole proprietor: it does **not** exist in KRS, and resolves through the
CEIDG/Biała-Lista path.

## Capabilities

| Capability | Status |
|-----------|--------|
| `lookup_by_identifier` (KRS) | ✅ Live — KRS REST |
| `lookup_by_identifier` (NIP / VAT) | ✅ Live — company (→KRS) **and** sole trader (→Biała Lista), key-free |
| `lookup_by_identifier` (REGON) | ✅ Live — key-free via Biała Lista (was: not implemented) |
| `search_by_name` (companies) | ✅ Live — GLEIF (LEI-registered → KRS), key-free |
| `search_by_name` (sole traders) | ✅ Live **with `PL_CEIDG_TOKEN`** — CEIDG v3 name search |
| `fetch_financials` (companies) | ✅ Live — OdpisPelny mentions + downloadable MSiG gazette PDFs |
| `fetch_financials` (sole traders) | ✅ Returns `[]` honestly — JDG file no public statements |

## Known limitations

- **Sole-trader NAME search needs `PL_CEIDG_TOKEN`.** No free source indexes
  CEIDG by name without it: the CEIDG public web search is CAPTCHA-walled,
  Biała Lista and GUS BIR only accept identifiers (NIP/REGON), and commercial
  aggregators (ALEO, rejestr.io) are Cloudflare-/key-gated. With the free
  token, `search_by_name("AKTIV JUSTYNA OSIP")` returns the sole trader.
  Without it, sole traders still resolve fully **by NIP or REGON**.
- **Biała Lista returns the owner's legal name, not the trade name.** For
  `AKTIV JUSTYNA OSIP` the key-free NIP/REGON lookup yields `JUSTYNA OSIP`
  (the taxpayer name) plus REGON, address, registration date, VAT status and
  bank accounts. CEIDG enrichment (token) overlays the full `AKTIV JUSTYNA
  OSIP` trade name and PKD codes.
- **Company name search covers LEI-registered entities only** (GLEIF →
  `RA000484` → KRS). SMEs without an LEI won't surface in company name
  search; lookup by KRS/NIP/REGON still works for them.
- **Company financials are filing metadata + the official gazette PDF, not
  parsed numbers.** Parsing statement line-items (iXBRL) is future work.
- **PESEL / surnames are masked** by the KRS API itself (by design).

## Status

🟢 **LIVE** — resolves any Polish business:

- Companies: KRS REST lookup, GLEIF name search, OdpisPelny + MSiG filings —
  all key-free.
- Sole traders (JDG): **key-free** lookup by NIP **and REGON** via Biała
  Lista; **name search + rich detail via CEIDG v3** once the free
  `PL_CEIDG_TOKEN` is set.

**Next steps:** provision `PL_CEIDG_TOKEN` in production to enable sole-trader
name search; parse MSiG/RDF PDFs into structured line-items (iXBRL) for real
balance-sheet numbers.
