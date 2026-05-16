# Austria — Firmenbuch / VIES

## Identifiers

- **Firmenbuchnummer (FN)** — digits (1–6) + optional check letter, e.g.
  `FN 81476 a`. Mapped to `IdentifierType.COMPANY_NUMBER`. Canonical form
  used by the adapter is `<digits><letter>` lower-case (no spaces, no
  "FN" prefix), e.g. `81476a`.
- **UID (Austrian VAT)** — `ATU` + 8 digits, e.g. `ATU12832407`. Mapped to
  `IdentifierType.VAT`. Canonical form in the adapter is `U########`
  (no `AT` prefix), VIES wants the country code separately.

## Sources

- **VIES** (https://ec.europa.eu/taxation_customs/vies/) — SOAP. Free, no
  auth. Validates AT UIDs. Austria participates in the privacy-restricted
  group (AT/DE/ES/CY): VIES does **not** return company name or address
  for AT, it only returns the validity flag. The adapter still surfaces
  the validity signal and any redacted-string protection on `---`.
- **Firmenbuch / Justizonline** (https://justizonline.gv.at/) —
  authoritative court business register. Requires ID-Austria / citizen-
  card login for structured extracts. **Not usable** in the free MVP.
- **OffeneRegister.at** — community Firmenbuch mirror referenced in
  research. Domain currently does not resolve (DNS dead) so cannot be
  used as a live source.
- **Wiener Börse** (https://www.wienerborse.at/) — hosts listed-issuer
  annual reports as PDFs but only behind TYPO3-rendered issuer pages with
  no stable filings index. Too brittle to scrape per project rules.
- **Paid alternatives (out of scope)**: Compass.at, KSV1870, Creditsafe AT,
  Firmenbuch full extracts (€1–€10/doc).

## Capabilities

| Capability     | State              | Reason |
| -------------- | ------------------ | ------ |
| `search`       | not_implemented    | No free JSON name-search exists; Justizonline needs eID. |
| `lookup` (VAT) | ok                 | VIES validates UID. AT VIES redacts name/address. |
| `lookup` (FN)  | not_implemented    | Firmenbuch needs ID-Austria; OffeneRegister.at offline. |
| `financials`   | empty list (best effort) | Filed Jahresabschluss is paid; Wiener Börse has no stable feed. |

## Test companies

- OMV AG — FN 81476 a, VAT `ATU12832407`
- Erste Group Bank AG — FN 33209 m, VAT `ATU14660509`
- voestalpine AG — FN 66209 t, VAT `ATU14809701`
- Vienna Insurance Group AG — FN 75687 f, VAT `ATU14624500`

VIES may mark any of these as invalid at any time if registration changes;
the adapter never invents a record when VIES returns `valid=false`.

## Status

Partial — VAT validation only. Health: `ok` when VIES is reachable,
`degraded` otherwise.

**Recommended next steps:**

1. Wire up a paid Compass.at or KSV1870 client behind a feature flag for
   real Firmenbuch lookup + filings (Phase 2, requires a commercial
   contract).
2. If OffeneRegister.at comes back online, add it as a free secondary
   source for FN → name/address resolution (still not for filings).
3. Build a generic European PDF-annual-report ingestion worker
   (Wiener Börse, Bundesanzeiger DE, BORME ES) so listed-company filings
   can be fetched out-of-band without per-issuer scraping in the request
   path.
