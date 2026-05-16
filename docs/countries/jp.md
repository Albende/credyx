# 🇯🇵 Japan — NTA Houjin-Bangou + FSA EDINET

## Identifiers

- Primary: `COMPANY_NUMBER` — 法人番号 (Hojin-bangō), 13 digits, e.g.
  `1180301018771` (Toyota Motor Corporation).
- Secondary: `OTHER` — EDINET code (`E` + 5 digits, e.g. `E02144`).
  Listed companies only. The MVP uses `IdentifierType.OTHER` since there
  is no dedicated EDINET enum.

Normalization: strip whitespace, hyphens, and a leading `JP` prefix;
require exactly 13 digits for Hojin-bangō.

## Sources

### Registry — National Tax Agency Houjin-Bangou Web-API v4

- Base: `https://api.houjin-bangou.nta.go.jp/4`
- Search by name: `GET /name?id={appId}&name={kanji_or_kana}&type=12&mode=2`
- Lookup by number: `GET /num?id={appId}&number={13digits}&type=12`
- Format: `type=12` requests JSON (default is CSV).
- **Auth**: free application ID via https://www.houjin-bangou.nta.go.jp/webapi/
- **Env var**: `JP_HOJIN_BANGO_APP_ID`
- **Rate limit**: ~5 req/sec official; we throttle to 60 req/min
  conservatively (`rate_limit_per_minute = 60`).
- **Returns**: name, kana, registered address (prefecture/city/street),
  status, assignment date, change history. **No financials.**

### Financials — FSA EDINET v2

- Base: `https://disclosure.edinet-fsa.go.jp/api/v2`
- Daily filings list: `GET /documents.json?date=YYYY-MM-DD&type=2`
- Document download (XBRL ZIP): `GET /documents/{docID}?type=1`
- Document download (PDF): `GET /documents/{docID}?type=2`
- **Auth**: none.
- **Rate limit**: undocumented but enforced — we throttle to 60 req/min
  and sleep 100 ms between probe-date scans.
- **robots.txt / ToS**: API explicitly documented for public consumption;
  we only fetch metadata, never the payload, inside `fetch_financials`.

EDINET strategy (MVP):

The EDINET v2 list endpoint is **date-scoped** — there is no native
"filings by edinet code over the last N years" call. Scanning all 365×N
days is impractical. We probe a small set of likely Yuho (annual
report, `docTypeCode=120`) submission dates per year:

- 30 June  — Mar-end fiscal year (the dominant Japanese FY pattern)
- 31 August — Jun-end FY
- 30 November — Sep-end FY
- 28 February — Dec-end FY

For each probe date in the trailing `years + 1` window we filter the
daily list by EDINET code (if known) or by `filerName` substring of the
NTA name. Annual Yuho filings are returned as `FinancialFiling` records
pointing at the EDINET ZIP URL — we do **not** download the payload.

**Coverage caveats**:

- Only **listed companies** filing on EDINET are covered. Non-listed
  private companies have no public free financial source in Japan.
- Companies with off-calendar reporting (e.g. early-Sep or mid-month
  filings) may be missed by the date probes — false-negative risk on
  edge-FYE companies. Acceptable trade-off for MVP; switch to a
  per-month-end full scan in Phase 2.
- Quarterly reports (`docTypeCode=140`) are skipped — annual only.
- Synthetic `period_end` falls back to `submitDateTime` when EDINET's
  `periodEnd` is missing.

## Test companies

- Toyota Motor Corporation — Hojin-bangō `1180301018771`, EDINET `E02144`
- Sony Group Corporation — Hojin-bangō `7010401114435`, EDINET `E01777`
- Nintendo Co., Ltd. — Hojin-bangō `4130001000022`, EDINET `E02367`
- SoftBank Group Corp — Hojin-bangō `9010001050624`, EDINET `E02778`

## Status

✅ **Live** — search + lookup (NTA), financials (EDINET annual Yuho URLs).

**Recommended next steps**:

1. Wire the ESEF/XBRL parser (`packages/risk/xbrl_esef.py`, planned) to
   actually parse EDINET ZIPs into `structured_data`.
2. Cache the NTA → EDINET code mapping nightly so we can stop probing
   by filer name and switch to direct `edinetCode` filtering.
3. Add a fallback path for companies with non-standard fiscal year ends
   (full month-end scan in Celery).
