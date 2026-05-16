# Iceland — Skatturinn Fyrirtækjaskrá + Nasdaq Iceland

## Identifier

- Types: `COMPANY_NUMBER` (primary) and `VAT` — both backed by the same number.
- Format: **kennitala**, 10 digits, conventionally rendered `DDMMYY-NNNN`.
  - First six digits are the date of incorporation (day, month, year).
  - For legal persons, `DD` is the real day plus 40 (range 41–71); this is
    how a kennitala for a company is distinguished from one for a natural
    person.
  - Digits 7–9 are a serial; digit 10 is a mod-11 checksum; the final
    digit is a century code (`9` = 1900s, `0` = 2000s).
- Example: `620483-0369` = Marel hf.

## Sources

### Skatturinn (RSK) Fyrirtækjaskrá / VSK-skrá
- Public name search: <https://www.skatturinn.is/fyrirtaekjaskra/leit/>
- Per-kennitala detail: `/fyrirtaekjaskra/leit/uppfletting/?kt={kennitala}`
- **Auth**: None.
- **Cost**: Free.
- **Format**: HTML only — no documented JSON API.
- **Rate limit**: Not published; adapter throttles to 30/min.
- **robots.txt / ToS**: Allowed for respectful crawling; the MVP does
  **not** scrape it. `search_by_name` and `lookup_by_identifier` therefore
  raise `AdapterNotImplementedError` until either Skatturinn publishes a
  JSON API or scraping infrastructure (Playwright + ToS review) lands.

### Nasdaq Iceland (OMXI)
- <https://www.nasdaqomxnordic.com/>
- **Auth**: None.
- **Cost**: Free.
- Per-issuer microsite carries annual reports and company news. The
  adapter emits one filing per year over the requested window, pointing
  at the per-issuer landing URL, only when the issuer's profile probe
  returns 200. Unlisted firms get `[]` — never a fabricated filing.
- **Opt-in hint**: callers route a listed issuer with
  `fetch_financials("NASDAQ:{ticker}")`, e.g. `NASDAQ:ARION`. A bare
  kennitala without the hint returns `[]` because there is no free
  kennitala-to-ticker map.

## Test companies

| Name | Kennitala | Nasdaq ticker (where listed) |
|------|-----------|-------------------------------|
| Marel hf.            | 620483-0369 | MAREL (Euronext primary; AMS) |
| Arion banki hf.      | 581008-0150 | ARION                          |
| Icelandair Group hf. | 631205-1780 | ICEAIR                         |
| Síminn hf.           | 460207-0810 | SIMINN                         |

## Status

🟡 **Partial** — kennitala normalization ✅; per-kennitala name/lookup is
blocked by lack of a free JSON API (raises 501); financials best-effort
via Nasdaq Iceland landing URLs for listed issuers only.

**Recommended next steps:**

1. Wire Playwright-based scraping for `/fyrirtaekjaskra/leit/` once the
   shared browser pool lands (`packages/adapters/_base/browser.py`). At
   that point `search_by_name` and `lookup_by_identifier` can return real
   `CompanyMatch` / `CompanyDetails` from the public detail page.
2. Plug Ársreikningaskrá (annual-accounts registry, also run by
   Skatturinn — RSK) into `fetch_financials` once their bulk feed is
   characterized; today it is PDF-only and requires the PDF text
   extraction pipeline that the roadmap defers to cross-cutting infra.
3. Mod-11 kennitala checksum verification — currently the shape is
   strict (10 digits) but the check digit is not validated. Add a
   `_kennitala_checksum_ok` helper once needed for input sanitization.
