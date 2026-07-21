# 🇩🇴 Dominican Republic — DGII + BVRD

## Identifier

- Type: `VAT` (RNC) — also surfaced as `COMPANY_NUMBER`.
- Format: 9–11 digits (corporate RNC = 9; cédula-derived RNC = 11).
  Examples: `101010632` (Banco Popular Dominicano),
  `101003723` (Cervecería Nacional Dominicana).

## Sources

- **DGII** — Dirección General de Impuestos Internos, RNC consultation:
  `https://dgii.gov.do/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/rnc.aspx`
  The consultation is an ASP.NET WebForm whose search runs through an MS-AJAX
  `UpdatePanel` partial postback (ScriptManager `ctl00$smMain`, panel
  `ctl00$cphMain$upBusqueda`). The adapter GETs the page to lift the
  `__VIEWSTATE` / `__VIEWSTATEGENERATOR` / `__EVENTVALIDATION` tokens, then
  POSTs them back with `__ASYNCPOST=true` and the target button as
  `__EVENTTARGET`. The response is the MS-AJAX delta; the RNC lookup returns a
  `dvDatosContribuyentes` detail table and the name search returns the
  `cphMain_gvBuscRazonSocial` grid. No API key, no CAPTCHA. A browser
  `User-Agent` is required — the WAF returns HTTP 500 to the partial postback
  under the default crawler UA.
  - The daily master roster `DGII_RNC.zip`
    (`https://www.dgii.gov.do/app/WebApps/Consultas/RNC/DGII_RNC.zip`, ~22 MB,
    pipe-delimited `RNC|Name|CommercialName|Activity|…|Status|Regime`) remains
    the authoritative bulk source for offline name search / verification.
- **BVRD** — Bolsa y Mercados de Valores de la República Dominicana:
  `https://bvrd.com.do/` — each listed issuer has a public
  `bvrd.com.do/downloads/{slug}/` "Estados Financieros" page hosting its filed
  statements as PDFs (WordPress Download Manager). The site is behind
  Cloudflare, so BVRD pages are fetched through the shared FlareSolverr bypass;
  the returned `cf_clearance` cookie + user-agent are reused with httpx to
  verify each PDF actually downloads before a `document_url` is emitted.
  Financials exist only for BVRD-listed issuers (banks, power generators, a few
  corporates and trusts).
- **Auth**: None.
- **Rate limit**: Self-imposed 30 req/min.
- **robots.txt / ToS**: Consultation page is public; bulk scraping is not
  encouraged — use `DGII_RNC.zip` for bulk use cases.

## Test companies

- Banco Popular Dominicano — RNC `101010632` (DGII lookup + BVRD financials)
- Cervecería Nacional Dominicana — RNC `101003723` (DGII lookup/search;
  not BVRD-listed, so `fetch_financials` → `[]`)
- Empresa Generadora de Electricidad Haina (Haina Investment Co.) — BVRD-listed

## Status

🟢 **Live** —
- `search_by_name` → DGII consultation grid (real matches; needs ≥4 chars).
- `lookup_by_identifier(VAT)` → DGII consultation detail record (razón social,
  nombre comercial, estado, actividad económica, régimen de pagos, admin local,
  facturador electrónico). Returns `None` when the RNC is not registered.
- `fetch_financials` → resolves the RNC's name to a BVRD issuer, opens its
  "Estados Financieros" downloads page, and returns `FinancialFiling` metadata
  (year, statement type, `period_end` when a month is named, and a verified
  `document_url` PDF) for the most recent `years`. Empty list for companies
  that are not BVRD-listed.
- `health_check` → probes the DGII consultation WebForm.

## Notes / next steps

- Financials require FlareSolverr (Cloudflare on BVRD). SIMV portals
  (`simv.gob.do`, `seri.simv.gob.do`, `mercadodevalores.simv.gob.do`) are the
  regulator's fuller filing archive but are Cloudflare-banned for datacenter
  IPs even through FlareSolverr — BVRD is the reachable free source.
- RNC→issuer resolution is a token-overlap match against the live BVRD issuer
  list; only ~30 issuers exist, so false matches are guarded by a 0.6 overlap
  threshold.
- For statements whose filename carries no explicit period, the year falls back
  to the document's publication timestamp (`ind=` epoch-ms on the download URL).
