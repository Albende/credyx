# Italy — VIES + Borsa Italiana / CONSOB

## Identifiers

- `VAT` (Partita IVA) — 11 digits, optional `IT` prefix. Last digit is a
  Luhn-style mod-10 check (odd positions summed as-is; even positions
  doubled with the digits of the product summed individually).
- `COMPANY_NUMBER` (Codice Fiscale) — for legal entities this is the same
  11-digit string as the Partita IVA. The 16-character individual Codice
  Fiscale is out of scope.
- `REA` (Repertorio Economico Amministrativo) — per-chamber, only via paid
  InfoCamere — not supported.

## Sources

- **VIES VAT validator** (SOAP, free, no auth):
  `https://ec.europa.eu/taxation_customs/vies/services/checkVatService`.
  Country code `IT`. Returns registered name + address for valid Partite
  IVA.
- **Borsa Italiana** (free, per-issuer scheda page):
  `https://www.borsaitaliana.it/borsa/azioni/scheda/{ISIN}.html`. Annual
  reports are linked from each page; per-document URLs require HTML
  parsing.
- **CONSOB** (free, regulator publications for Italian listed issuers):
  `https://www.consob.it/web/area-pubblica/emittenti`.
- **Registro Imprese / InfoCamere** — **paid, not used.** Full registry,
  filings, and ownership data are behind a per-query commercial tariff,
  which the MVP rules forbid.

## Rate limit

30 requests/minute (VIES is shared EU infrastructure; be polite).

## Test companies

- Eni S.p.A. — Partita IVA `00484960588` (ISIN `IT0003132476`)
- Enel S.p.A. — Partita IVA `00811720580` (ISIN `IT0003128367`)
- Intesa Sanpaolo S.p.A. — Partita IVA `00799960158` (ISIN `IT0000072618`)
- UniCredit S.p.A. — Partita IVA `00348170101` (ISIN `IT0005239360`)

## Status

- ✅ **VAT lookup** via VIES — name + address for any valid Partita IVA.
- 🟡 **Financials** — listed-only, via Borsa Italiana scheda pages.
  Per-document PDF/XBRL URLs require HTML parsing (follow-up once the
  scraper pool lands). Unlisted entities return `[]`.
- 🔴 **Name search** — no free authoritative API. `search_by_name` raises
  `AdapterNotImplementedError`. Use OpenCorporates global search or look
  up by Partita IVA.

**Recommended next step (Phase 2):** Wire ESEF iXBRL parsing for Borsa
Italiana annual reports so listed-issuer financials become structured
instead of pointer-only; revisit InfoCamere only as a paid Phase-2
decision.
