# Portugal — VIES + CMVM

## Identifier

- Type: `VAT` (NIPC) / `COMPANY_NUMBER` (NIPC)
- Format: 9 digits. NIPC also serves as VAT when prefixed with `PT`.
- Checksum: weights `9,8,7,6,5,4,3,2` against the first eight digits;
  sum mod 11; if remainder < 2 the check digit is 0, else `11 - remainder`.

## Sources

| Endpoint | Use | Auth | Cost |
|----------|-----|------|------|
| `POST https://ec.europa.eu/taxation_customs/vies/services/checkVatService` (SOAP) | VAT/NIPC validation + registered name/address | None | Free |
| `https://web3.cmvm.pt/sdi/emitentes/index.cfm?dispatch=bynif&nif={NIPC}` | Listed-issuer disclosure page (annual reports, iXBRL) | None | Free |

Rate limit: throttled in-adapter to 30 req/min (VIES rejects bursts).

## Test companies

| NIPC | Name |
|------|------|
| `500697256` | EDP — Energias de Portugal, S.A. |
| `504499777` | Galp Energia, SGPS, S.A. |
| `500100144` | Jerónimo Martins, SGPS, S.A. |
| `501525882` | Banco Comercial Português, S.A. (Millennium BCP) |

## Status

- ✅ **VAT/NIPC lookup** — VIES SOAP, returns name + registered address.
- 🟡 **Financials** — listed-issuer-only pointers to the CMVM disclosure
  page (`document_format="html"`). Per-document PDF / iXBRL URLs need
  HTML parsing of the issuer page; deferred until the PDF / ESEF
  pipeline lands.
- 🔴 **Name search** — no free authoritative source. IRN / Registo
  Comercial Online charges per certificate; Portal da Empresa exposes
  only interactive search behind a CAPTCHA. `search_by_name` raises
  `AdapterNotImplementedError`. Use OpenCorporates global search or
  look up directly by NIPC.

**Recommended next step:** add per-issuer PDF discovery on CMVM and pipe
the documents through the (not-yet-wired) iXBRL ESEF parser once
available.
