# Denmark — CVR (Det Centrale Virksomhedsregister)

## Status

LIVE — wired against `distribution.virk.dk` ElasticSearch with HTTP
Basic auth.

## Identifier

- Primary: **CVR-nummer** — 8 digits (`COMPANY_NUMBER`).
- Also accepted: **VAT** — `DK` + CVR (e.g. `DK22756214`). The adapter
  strips the `DK` prefix during normalization.

## Source

- ElasticSearch search:
  `http://distribution.virk.dk/cvr-permanent/virksomhed/_search`
  (POST JSON body, ES DSL).
- Annual report catalogue fallback:
  `https://regnskaber.virk.dk/api/regnskaber?cvr={cvr}` — public, no auth
  required for the JSON list or for downloading the PDF/XBRL blobs.
- Human-facing: `https://datacvr.virk.dk/enhed/virksomhed/{cvr}`.

## Auth

- HTTP Basic — credentials issued **free of charge** by Erhvervsstyrelsen
  on request.
- Sign-up:
  https://datacvr.virk.dk/data/cvr-hjaelp/sadan-soger-du-data-fra-cvr-permanent
- Environment variables:
  - `DK_VIRK_USERNAME`
  - `DK_VIRK_PASSWORD`
- Both are required. `health_check` returns `DEGRADED` if either is
  missing.

## Rate limits

- Documented at ~3 req/sec. We throttle adapter-side to
  `rate_limit_per_minute = 60`.
- `get_with_retry` / response status 429 honors `Retry-After`.

## Capabilities

| Capability | Supported |
|------------|-----------|
| Search by name | Yes (match query on `Vrvirksomhed.navne.navn`) |
| Lookup by CVR | Yes (term query on `Vrvirksomhed.cvrNummer`) |
| Lookup by VAT (`DK` + CVR) | Yes — VAT prefix is stripped |
| Annual reports | Yes — pulled from `regnskaber` array on CVR record, falls back to `regnskaber.virk.dk` catalogue |
| Structured XBRL parsing | No (PDF/XBRL URLs only; parsing happens downstream) |

## Test companies

| Company | CVR | VAT |
|---------|-----|-----|
| A.P. Møller - Mærsk A/S | 22756214 | DK22756214 |
| Carlsberg A/S | 61056416 | DK61056416 |
| Novo Nordisk A/S | 24256790 | DK24256790 |
| LEGO A/S | 54562519 | DK54562519 |

## Local setup

```bash
export DK_VIRK_USERNAME=...   # provided by Erhvervsstyrelsen
export DK_VIRK_PASSWORD=...

# Smoke test
PYTHONPATH=. pytest packages/adapters/dk -m integration
```

## Known limitations

- The CVR ES distribution sometimes returns HTML on outage; the adapter
  catches JSON-parse failure and surfaces `AdapterError`.
- The `regnskaber` array embedded in CVR records does not always carry
  document URLs — we fall back to the public `regnskaber.virk.dk` JSON
  catalogue in that case.
- XBRL of annual reports is downloadable without auth, but parsing the
  Danish XBRL taxonomy is out of scope for the MVP; `structured_data` is
  `None` and the document URL is exposed for downstream extraction.
