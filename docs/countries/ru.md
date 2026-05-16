# 🇷🇺 Russia — FNS (Federal Tax Service) registries

## Identifier

- **INN** — Идентификационный номер налогоплательщика. Mapped to
  `IdentifierType.VAT`. 10 digits for legal entities, 12 digits for
  individuals / sole proprietors. Mod-11 check digit(s) validated
  per FNS order ММВ-7-6/435@; the adapter rejects any INN that fails
  the checksum before issuing a network request.
- **OGRN** — Основной государственный регистрационный номер. Mapped to
  `IdentifierType.COMPANY_NUMBER`. 13 digits for legal entities,
  15 digits for sole proprietors (OGRNIP).
- **KPP** — Код причины постановки на учёт. 9 digits, branch
  identifier paired with INN. Returned in the registry payload as
  `IdentifierType.OTHER` but not accepted as a primary lookup key.

`RU` prefix on either identifier is stripped before validation.

## Sources

- https://egrul.nalog.ru/ — Unified State Register of Legal Entities
  (ЕГРЮЛ) and Individual Entrepreneurs (ЕГРИП). Public web portal of
  the Federal Tax Service. Free, no auth.
  - Internal AJAX protocol used here:
    1. `POST https://egrul.nalog.ru/` with form-encoded body
       `query=<INN|OGRN|name>` → returns `{"t": "<token>"}`.
    2. `GET https://egrul.nalog.ru/search-result/{token}` →
       returns `{"rows": [...], "status": 0|1}`. `status=1` means
       still computing; the adapter polls with short back-offs.
- https://bo.nalog.ru/ — ГИРБО, State Information Resource for
  Accounting Reports. Free PDF / Excel downloads of annual accounts
  filed to the FNS since 2019.
  - `POST/GET /nbo/organizations/search?query=<INN>&page=0`
  - `GET /nbo/organizations/{id}/bfo/`
  - `GET /nbo/bfo/{report_id}/transformation-file/` (raw document).
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min. Neither portal publishes
  a budget; both serve a public registry and can geo-throttle.
- **robots.txt / ToS**: Both portals are statutory public registries
  operated by the FNS. We send a clearly identifiable User-Agent and
  use the same JSON endpoints the official web client uses.

## Financials

Annual accounting reports (Бухгалтерская (финансовая) отчётность)
filed with the FNS since 2019 are published free at bo.nalog.ru.
`fetch_financials` returns one `FinancialFiling` per filed year, with
the FNS `transformation-file` URL as `document_url` (`document_format`
= "pdf"; the same endpoint also serves the original XLS-derived file).
PDF text extraction is not yet wired in — see the cross-cutting infra
notes in CLAUDE.md.

Pre-2019 statements were filed with Rosstat (state statistics service)
and are not centrally republished for free.

## Test companies

- Sberbank PAO — INN `7707083893`, OGRN `1027700132195`
- Gazprom PAO — INN `7736050003`, OGRN `1027700070518`
- Rosneft PAO — INN `7706107510`, OGRN `1027700043502`
- Yandex LLC (Russian subsidiary of Yandex N.V.) — INN `7736207543`,
  OGRN `1027700229193`

All four INNs validate against the Mod-11 checksum (asserted in the
unit-test suite).

## Status

🟢 **Live** — search + lookup + financials.

| Capability  | Status                                          |
|-------------|-------------------------------------------------|
| Name search | ✅ Live (egrul.nalog.ru two-step JSON)          |
| INN lookup  | ✅ Live (egrul.nalog.ru)                        |
| OGRN lookup | ✅ Live (egrul.nalog.ru)                        |
| Financials  | ✅ Live (bo.nalog.ru, PDF document URLs, 2019+) |
| Health      | ✅ Probes Sberbank INN                          |

## Limitations

- **Two-step search adds latency.** EGRUL's POST/GET token protocol
  costs ~600–1200 ms per query; the adapter polls up to ~3 seconds
  before giving up.
- **Schema drift.** EGRUL's row payload uses short Cyrillic-inspired
  keys (`n` / `i` / `o` / `p` / `a` / `g` / `ok` / `st`). The adapter
  matches loosely on a small allowlist of known variants.
- **Geo-blocking and CAPTCHA.** Both portals occasionally rate-limit
  or challenge non-Russian IPs; persistent blocks should be treated
  as `BLOCKED`. The adapter does not solve CAPTCHAs.
- **No structured XBRL.** bo.nalog.ru ships PDF and a proprietary
  transformation file, not iXBRL. Number extraction requires the
  pypdf / pdfplumber pipeline noted in CLAUDE.md.
- **Sanctions context.** A large share of Russian legal entities
  listed on egrul.nalog.ru are subject to EU / UK / US / Swiss
  sanctions, including all four test companies (Sberbank, Gazprom,
  Rosneft, Yandex's parent). Registry data is factual and
  non-sanctioned; downstream consumers MUST run OpenSanctions
  screening before any credit decision. The risk engine should
  surface a high-severity red flag whenever a Russian counterparty
  is in scope.

## Recommended next steps

1. Wire OpenSanctions screening for every RU lookup at the risk-engine
   layer — same hook envisioned for Belarus and Iran.
2. Plug the global PDF text-extraction pipeline into the
   `transformation-file` URL so the LLM can read balance-sheet line
   items.
3. Add a structured ratio parser specific to the FNS form layout
   (forms 1 and 2, ОКУД 0710001 / 0710002) — these are highly
   regular and amenable to deterministic XLS parsing.
