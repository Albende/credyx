# 🇰🇷 South Korea — OpenDART (FSS)

## Identifiers

- Type: `COMPANY_NUMBER` — OpenDART `corp_code`, 8 digits, zero-padded.
  Internal FSS code (e.g. 00126380 = Samsung Electronics).
- Type: `OTHER` — Stock code (ticker), 6 digits, for KOSPI/KOSDAQ/KONEX
  listed firms (e.g. 005930 = Samsung Electronics).
- Type: `VAT` — 사업자등록번호 (Business Registration Number), 10 digits,
  conventionally formatted XXX-XX-XXXXX. Returned in lookup payloads but
  not directly resolvable to a `corp_code` via OpenDART.

## Sources

- https://opendart.fss.or.kr — REST API over FSS DART filings.
- **Auth**: Yes — `KR_OPENDART_API_KEY` (free, instant signup at
  https://opendart.fss.or.kr/uss/umt/EgovMberInsertView.do).
- **Rate limit**: 10,000 requests / day / key (adapter throttles to
  100 req/min).
- **robots.txt / ToS**: API use is explicitly permitted with a registered
  key; bulk scraping of the dart.fss.or.kr UI is discouraged.

## Endpoints used

| Purpose | Endpoint |
|---|---|
| Full corp-code list (ZIP/XML) | `GET /api/corpCode.xml` |
| Company registry info | `GET /api/company.json?corp_code=...` |
| Filing list (annual reports) | `GET /api/list.json?corp_code=...&pblntf_ty=A` |
| Structured financials (annual) | `GET /api/fnlttSinglAcnt.json?corp_code=...&bsns_year=YYYY&reprt_code=11011` |
| Document view (HTML) | `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...` |

OpenDART returns `{"status": "013", "message": "조회된 데이타가 없습니다"}` to
mean "no data" — the adapter treats that as empty rather than an error.
Auth/quota errors come back as `010`/`011`/`020`.

## Corp-code cache

OpenDART has no native fuzzy name search. The adapter calls
`/api/corpCode.xml` once per process, parses the embedded `CORPCODE.xml`
and keeps the list in memory on the class (`_corp_code_cache`). Name
searches are substring matches over that cache, preferring prefix matches
and listed companies. The full list is ~100k rows and parses in well
under a second.

## Test companies

| Name | corp_code | Stock |
|---|---|---|
| Samsung Electronics Co., Ltd. | 00126380 | 005930 |
| Hyundai Motor Company | 00164742 | 005380 |
| LG Electronics Inc. | 00401731 | 066570 |
| SK Hynix Inc. | 00164779 | 000660 |

## Status

✅ **Live** — search + lookup + structured annual financials (KRW) for
all FSS-reporting entities.

## Coverage caveats

- OpenDART only indexes entities that file with the FSS: all KOSPI/
  KOSDAQ/KONEX listed companies, plus large unlisted companies subject
  to external audit and certain other reporting types.
- **Small private firms** that have only a 사업자등록번호 and no FSS
  filing obligation are **not** in OpenDART. NTS/HomeTax-side
  Business-Registration lookups would be required and are out of scope
  for the free-source MVP.
- Reverse lookup VAT → corp_code is not supported by OpenDART; the
  adapter raises `InvalidIdentifierError` for that path and recommends
  using `COMPANY_NUMBER` or `OTHER` (stock code).

## Recommended next step

Wire the EDINET/DART-style annual-report HTML into the PDF/HTML text
extraction pipeline so the LLM can read narrative sections of 사업보고서
filings (management discussion, audit opinion) alongside the structured
balance sheet.
