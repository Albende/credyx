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
- https://www.cbr.ru/finorg/ — Bank of Russia (Центральный банк РФ)
  financial-organization disclosure portal. Every supervised financial
  entity (credit institution, NPF, insurer, MFO, broker, …) files its
  statutory reporting forms here. Free, no auth, internationally
  reachable.
  - `GET /finorg/foinfo/reports/?ogrn=<OGRN>` → HTML index listing every
    filed form. The adapter extracts the CBR `regnum` and the set of
    Форма 102 (statement of financial results) reporting dates.
  - `GET /banking_sector/credit/coinfo/f102?regnum=<regnum>&dt=YYYY-01-01`
    → the statement of financial results for the year `YYYY-1`
    (also f101 turnover balance, f123/f135 capital, f802/f803/f805
    consolidated).
- https://bo.nalog.gov.ru/ — ГИРБО, State Information Resource for
  Accounting Reports (non-financial companies' balance sheets since
  2019). **Geo-blocked**: the search index returns an empty result set
  to non-RU IPs (confirmed against a real browser session), so it is not
  usable from an ex-RU deployment and is not wired in. Use it only when
  the platform runs from a Russian egress.
- **Auth**: None.
- **Rate limit**: Self-imposed at 30 req/min. Neither portal publishes
  a budget; both serve a public registry and can geo-throttle.
- **robots.txt / ToS**: Both portals are statutory public registries
  operated by the FNS. We send a clearly identifiable User-Agent and
  use the same JSON endpoints the official web client uses.

## Financials

`fetch_financials` serves financial-sector counterparties from the Bank
of Russia disclosure portal (cbr.ru). It resolves the input INN/OGRN to
the entity's OGRN (via a single EGRUL round-trip when an INN is given),
loads `/finorg/foinfo/reports/?ogrn=`, and returns one `FinancialFiling`
per filed year — `type=ANNUAL_REPORT`, `currency="RUB"`, `period_end`
= 31 Dec of the year, and `source_url` pointing at that entity's official
Форма 102 statement of financial results (`.../coinfo/f102?regnum=<n>&dt=
YYYY-01-01`, which is the results for `YYYY-1`). No fabricated numbers are
returned; `structured_data`/`document_url` stay `None` until the CBR
form-102/101 HTML parser is wired in (see cross-cutting infra in
CLAUDE.md).

Non-financial companies (e.g. Gazprom, Rosneft) have no CBR disclosure;
their statutory accounts live in ГИРБО (bo.nalog.gov.ru), whose search
index is geo-blocked outside Russia (see Sources), so `fetch_financials`
returns an empty list for them from an ex-RU deployment rather than
inventing data. Pre-2019 statements filed with Rosstat are not centrally
republished for free.

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
| Name search | ✅ Live (egrul.nalog.ru two-step JSON)                    |
| INN lookup  | ✅ Live (egrul.nalog.ru)                                  |
| OGRN lookup | ✅ Live (egrul.nalog.ru)                                  |
| Financials  | ✅ Live for financial-sector entities (cbr.ru Форма 102) |
|             | ⚠️ Non-financial GIRBO needs a RU egress (geo-block)     |
| Health      | ✅ Probes Sberbank INN                                    |

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
- **Financials limited to the financial sector.** cbr.ru only discloses
  supervised financial organizations (banks, NPFs, insurers, MFOs, …).
  Non-financial companies' accounts are in ГИРБО, which geo-blocks
  ex-RU IPs, so their `fetch_financials` returns `[]` from outside
  Russia.
- **No structured numbers yet.** The adapter returns Форма 102 filing
  metadata + the official CBR source URL, not parsed line items. The
  CBR form-102/101 HTML tables are highly regular and amenable to a
  deterministic parser (see Recommended next steps).
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
