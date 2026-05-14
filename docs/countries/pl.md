# 🇵🇱 Poland — KRS + CEIDG + Biała Lista

## Identifier

- Type: `KRS / NIP / REGON`
- Format: KRS 10-digit; NIP 10-digit; REGON 9 or 14.

## Sources

- https://api-krs.ms.gov.pl ; https://prod.ceidg.gov.pl ; https://wl-api.mf.gov.pl
- **Auth**: KRS REST is public; CEIDG free; Biała Lista free.
- **Rate limit**: Varies.
- **robots.txt / ToS**: Open data — allowed.

## Test companies

- PKN Orlen S.A. (KRS 0000028860, NIP 7740001454); CD Projekt (KRS 0000006865); Allegro.eu (KRS 0000635012).

## Status

🔴 **Not yet wired** — KRS JSON endpoint reachable via api-krs.ms.gov.pl; would be highest-value next adapter.

**Recommended next step:** Implement KRS REST client + Biała Lista VAT validation for credit scoring.
