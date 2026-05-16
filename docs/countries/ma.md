# 🇲🇦 Morocco — OMPIC / DGI / AMMC

## Identifier

- Primary: `VAT` → ICE (Identifiant Commun de l'Entreprise), 15 digits.
  Issued since 2015, mandatory on every commercial document. Normalised
  by stripping whitespace, dashes, and an optional `MA` prefix.
- Secondary: `COMPANY_NUMBER` → RC (Registre du Commerce), formatted as
  `<tribunal> <digits>` (e.g. `Casablanca 123456`). Format varies by
  jurisdiction and is not enforced beyond non-empty.
- Also in circulation: IF (Identifiant Fiscal, tax number) — not
  exposed as its own `IdentifierType` since the ICE supersedes it for
  inter-company use.

## Sources

- **OMPIC** (Office Marocain de la Propriété Industrielle et
  Commerciale) — https://www.ompic.ma/ and https://www.directinfo.ma/.
  - Public name search exists but is throttled and the full commercial
    register is paid.
  - **Auth**: None for the landing page; paid subscription for
    `directinfo.ma` extracts.
  - **Rate limit**: Not published; adapter throttles to 30 req/min.
- **DGI** (Direction Générale des Impôts) ICE validator —
  https://www.tax.gov.ma/wps/portal/DGI/ICE.
  - HTML-only, often gated by a session token / CAPTCHA. Used
    best-effort by `lookup_by_identifier`; non-deterministic responses
    surface as `AdapterNotImplementedError`.
- **AMMC** (Autorité Marocaine du Marché des Capitaux) —
  https://www.ammc.ma/. Free annual / reference documents for issuers
  listed on the Bourse de Casablanca.
- **Bourse de Casablanca** — https://www.casablanca-bourse.com/. Free
  issuer pages with annual reports keyed by ticker.

## Test companies

- Maroc Telecom (Itissalat Al-Maghrib) — ICE `001525713000050`,
  ticker `IAM`.
- Attijariwafa Bank — ICE `001084283000004`, ticker `ATW`.
- OCP Group (Office Chérifien des Phosphates) — ICE `000000067000049`
  (state-owned, not listed on BVC equity board).
- BMCE Bank of Africa — ICE `001561033000010`, ticker `BCP` /
  `BOA`-rebrand.

## Status

🟡 **DEGRADED** — listed-issuer financials are linkable via AMMC and
Bourse de Casablanca; the commercial register itself is paid, so name
search is intentionally a 501.

**Capabilities**
- `search_by_name` — **Not implemented.** Raises
  `AdapterNotImplementedError`. No free clean API exists; OMPIC's
  `directinfo.ma` requires a paid subscription.
- `lookup_by_identifier(VAT, ice)` — Best-effort GET to the DGI
  validator. If the response is not machine-parseable (CAPTCHA,
  session redirect, empty body) raises `AdapterNotImplementedError`
  rather than returning a fabricated record.
- `lookup_by_identifier(COMPANY_NUMBER, rc)` — Raises
  `AdapterNotImplementedError`; RC resolution requires OMPIC paid
  access.
- `fetch_financials(ice)` — Returns `[]` for non-listed companies (a
  factual "no public filings" answer). Listed issuers via AMMC /
  Bourse de Casablanca are pending an ICE→ticker resolver and are
  the natural next step.

**Known gaps / next steps**
- Paid OMPIC subscription would unlock name search and RC lookups.
  Phase-2 decision, blocked by the no-paid-API MVP rule.
- Build an ICE→Bourse-de-Casablanca-ticker map (small fixed list,
  ~80 issuers) to enable real `fetch_financials` for listed firms.
- AMMC publishes reference documents (« document de référence ») as
  PDFs; wiring the PDF pipeline once `pypdf` is enabled would
  surface ratios for the listed cohort.
