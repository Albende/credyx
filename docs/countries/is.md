# Iceland — Skatturinn Fyrirtækjaskrá + Ársreikningaskrá

## Identifier

- Types: `COMPANY_NUMBER` (primary) and `VAT`.
  - `COMPANY_NUMBER` is the **kennitala** (10 digits, `DDMMYY-NNNN`).
  - `VAT` is the separate **VSK-númer** (a short registration number, e.g.
    `IS10744`) surfaced from the company's VAT-registration table — it is
    *not* the kennitala, contrary to a common misconception.
- Kennitala format: 10 digits, conventionally rendered `DDMMYY-NNNN`.
  - First six digits are the date of incorporation (day, month, year).
  - For legal persons, `DD` is the real day plus 40 (range 41–71); this is
    how a kennitala for a company is distinguished from one for a natural
    person.
  - Digits 7–9 are a serial; digit 10 is a mod-11 checksum; the final
    digit is a century code (`9` = 1900s, `0` = 2000s).
- Example: `620483-0369` = (JBT) Marel ehf.

## Sources

### Skatturinn (RSK) Fyrirtækjaskrá / Ársreikningaskrá / VSK-skrá
- Public name search: `GET https://www.skatturinn.is/fyrirtaekjaskra/leit/?nafn={name}`
  — returns an HTML table of `kennitala` / name (`Nafn`) / address (`Póstfang`)
  rows. Deregistered entities are flagged `(Félag afskráð)`.
- Per-kennitala detail:
  `https://www.skatturinn.is/fyrirtaekjaskra/leit/kennitala/{kennitala}` —
  carries the registered name, incorporation date (`Stofnað/Skráð`), legal
  form (`Rekstrarform`), domicile (`Lögheimili`), ÍSAT activity code, active
  VAT number, directors (`Forráðamaður`), and — under **Gögn úr
  ársreikningaskrá** — a table of every filed annual account
  (`Rek. ár` / `Skiladagsetning` / `Nr. ársreiknings` / `Tegund ársreiknings`).
  A kennitala that does not resolve returns the bare search form; the adapter
  detects that and returns `None` / `[]`.
- **Auth**: None. **Cost**: Free. **Format**: HTML (no JSON API).
- **Rate limit**: Not published; adapter throttles to 30/min. The site is
  mildly flaky under rapid sequential requests — `get_with_retry` covers
  transient transport errors.
- **robots.txt / ToS**: Public register, respectful crawling. The adapter
  parses the public detail/search HTML (no login, no automation of the
  paid/session flows).

### Annual-account PDFs (Ársreikningaskrá web-shop)
- The filed annual-account PDFs are **free** but are delivered through a
  stateful RSK web-shop: add the account number (`Nr. ársreiknings`) to a
  cart at `vefur.rsk.is/Vefverslun/`, confirm (price 0), then download via an
  ASP.NET postback. There is **no stable document URL** to persist, so
  `fetch_financials` returns the real per-company account metadata (fiscal
  year, type, filing date, official account number, registry `source_url`)
  with `document_url` left unset — never a fabricated or generic link.

## Test companies

| Name | Kennitala | Notes |
|------|-----------|-------|
| (JBT) Marel ehf.     | 620483-0369 | ~51 filed annual accounts from 1995 on |
| Arion banki hf.      | 581008-0150 | Bank; annual + consolidated accounts |
| Icelandair Group hf. | 631205-1780 | Holding company |
| Síminn hf.           | 460207-0880 | Active telecom entity (the previously listed `460207-0810` no longer resolves) |

## Status

🟢 **Live** — `search_by_name`, `lookup_by_identifier` and
`fetch_financials` all return real data parsed from the public Skatturinn
register.

- `search_by_name` → parses the `?nafn=` results table (kennitala, name,
  address, deregistration flag).
- `lookup_by_identifier` → parses the per-kennitala detail page
  (name, legal form, incorporation date, domicile, ÍSAT/NACE code, VAT
  number, directors). Unknown kennitala → `None`.
- `fetch_financials` → parses **Gögn úr ársreikningaskrá**, one filing per
  fiscal year (preferring the standalone `Ársreikningur` over the
  `Samstæðureikningur`), with the official account number in
  `structured_data`.

**Recommended next steps:**

1. **Annual-account PDF retrieval.** Automate the free RSK web-shop checkout
   (cart → confirm → ASP.NET `Btn_Saekja` postback) in a Celery worker to
   pull the actual PDF for a given account number, then run it through the
   PDF text-extraction pipeline and attach structured figures. Until then
   `document_url` stays unset by design.
2. **Currency.** Icelandic filers report in ISK, EUR or USD depending on the
   entity (e.g. Marel reports in EUR); currency is left `None` rather than
   assumed. Populate it from the extracted statement once PDFs are parsed.
3. **Mod-11 kennitala checksum verification** — currently the shape is strict
   (10 digits) but the check digit is not validated.
