# 🇰🇭 Cambodia — Ministry of Commerce (MoC) + CSX

## Identifier

- Types: `COMPANY_NUMBER`, `VAT`.
- `COMPANY_NUMBER` (primary) — MoC registration number printed on the
  Certificate of Incorporation. Typically 8-digit zero-padded
  (e.g. `00012345`). The adapter accepts 6–10 digits and normalises to
  8 by zero-padding; `KH` prefix and separators (`- . space`) are
  stripped.
- `VAT` — Tax Identification Number issued by the General Department of
  Taxation (GDT). 9–10 digits, frequently colocated with the MoC number
  on the same record.

## Sources

- https://www.businessregistration.moc.gov.kh — MoC Online Business
  Registration portal. The adapter probes the public search endpoints
  (`/api/public/companies` and `/api/public/companies/search`) which the
  portal UI itself consumes. **Auth**: No. **Rate**: Adapter throttles
  to 30 req/min and honours `Retry-After`. If the upstream schema
  changes or the endpoints disappear, the adapter falls back gracefully
  and returns `[]` rather than guessing.
- https://csx.com.kh — Cambodia Securities Exchange. Listed issuers
  publish their annual reports under
  `/en/listed-companies/profile/{TICKER}`. Free, HTML-only. The adapter
  only emits a filing URL after probing the ticker landing page and
  confirming a 200 response.
- No paid sources used (no Acra-style commercial register, no D&B).

## Listed issuers known to the adapter

| Ticker | Company |
|--------|---------|
| `ABC`  | ACLEDA Bank Plc. |
| `PPSP` | Phnom Penh Special Economic Zone Plc |
| `PWSA` | Phnom Penh Water Supply Authority |
| `PAS`  | Sihanoukville Autonomous Port |
| `GTI`  | Grand Twins International (Cambodia) Plc |
| `PPAP` | Phnom Penh Autonomous Port |

The mapping is keyed on a slugified name so common spellings of these
issuers resolve even when the MoC payload omits a ticker.

## Test companies

- ACLEDA Bank Plc. — CSX: `ABC`
- PPSP (Phnom Penh Special Economic Zone Plc) — CSX: `PPSP`
- Phnom Penh Water Supply Authority — CSX: `PWSA`
- Sihanoukville Autonomous Port — CSX: `PAS`

## Status

✅ **Live (best-effort)** — name search and identifier lookup via the
MoC portal's public JSON endpoints; financials emitted only for
CSX-listed issuers whose ticker landing page returns 200. Unlisted
firms return `[]` (the rule: never fabricate filings for a credit
decision).

## Known limitations

- The MoC portal occasionally requires a session cookie before its
  search endpoints respond. When that happens the adapter sees a 4xx
  and returns `[]`; this is the same defensive contract used by the VN
  adapter and is consistent with the project rule that adapters never
  invent data.
- The portal payload's field names are not officially documented. The
  adapter `_pick`-s across the most common spellings seen in practice
  (`registration_number`, `regNo`, `name_en`, `address_en`, etc.).
- Khmer-language fields are preserved as UTF-8 and exposed via
  `CompanyDetails.raw`; the English `name_en` is preferred for `name`
  when present.

## Recommended next step

When the GDT publishes a public VAT lookup API, wire it as a secondary
verification source so a `VAT` lookup can confirm the MoC record's TIN.
For full filings of unlisted Cambodian firms, only paid MoC document
downloads exist today — out of scope for the free MVP.
