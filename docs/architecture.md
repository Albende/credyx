# CreditLens — Architecture

## Components

```
              ┌────────────────────────────┐
              │   Next.js 15 frontend      │
              │   apps/web (Tailwind, TS)  │
              └─────────────┬──────────────┘
                            │ HTTPS
              ┌─────────────▼──────────────┐
              │   FastAPI backend          │
              │   apps/api                 │
              │   - /api/countries         │
              │   - /api/search            │
              │   - /api/companies/...     │
              │   - /api/jobs/{id}         │
              └──┬─────────┬───────────┬───┘
                 │         │           │
        ┌────────▼──┐  ┌───▼────┐  ┌───▼────────────┐
        │ Postgres  │  │ Redis  │  │ Country        │
        │ 16        │  │ 7      │  │ adapters       │
        │ (cache,   │  │ (rate  │  │ packages/      │
        │  jobs)    │  │  limit)│  │ adapters/{cc}/ │
        └───────────┘  └────────┘  └─────┬──────────┘
                                         │
                            ┌────────────▼───────────────┐
                            │ External data sources       │
                            │ (Companies House, EDGAR,    │
                            │ INSEE, ARES, GLEIF, ...)   │
                            └─────────────────────────────┘

                            ┌─────────────────────────────┐
                            │ packages/risk + packages/llm│
                            │ — deterministic ratios      │
                            │ — Gemini via kie.ai         │
                            └─────────────────────────────┘
```

## Data flow for a risk analysis

1. **Search** → adapter returns `CompanyMatch[]`.
2. **Lookup** → adapter returns `CompanyDetails`, cached in `companies`.
3. **Financials** → adapter returns `FinancialFiling[]`, cached in
   `financial_filings`.
4. **Risk analysis** (POST):
   - Backend creates an `ingestion_jobs` row, returns `job_id`.
   - Background task loads cached filings, computes ratios deterministically
     (`packages.risk.ratios`).
   - Hands ratios + company context to `LLMService.analyze_credit_risk`.
   - LLM returns structured JSON conforming to `RiskAssessment` schema.
   - Backend writes `risk_assessments`, marks job `done` with the result.
5. **Poll** → `GET /api/jobs/{id}` returns the assessment.

## Why deterministic ratios first

Models hallucinate when asked to do arithmetic on long numeric tables. We
compute the ratios in pure Python and pass them as named context — the LLM's
only job is **interpretation**. This makes outputs reproducible and
much cheaper (smaller prompts, smaller responses).

## Caching

| Type         | Store    | Default TTL |
|--------------|----------|-------------|
| Company info | Postgres | 7 days      |
| Financials   | Postgres | 30 days     |
| Risk score   | Postgres | always kept (audit) |

Force-refresh on any endpoint with `?force_refresh=true`.

## Rate limiting

Redis sliding window per IP (default 60 req/min). Health and docs endpoints
are exempt. Fail-open if Redis is down.

## Adding a new country adapter

1. `mkdir packages/adapters/{cc}/`
2. Implement a class inheriting from `CountryAdapter`:
   - Set `country_code`, `country_name`, `identifier_types`,
     `primary_identifier`, optionally `requires_api_key` / `api_key_env`.
   - Implement `search_by_name`, `lookup_by_identifier`, `fetch_financials`.
3. Add to `packages/adapters/registry.py` → `_build_real_adapters`.
4. Add an integration test in `packages/adapters/{cc}/tests/`.
5. Document the registry in `docs/countries/{cc}.md`.
6. Run the validation script (`scripts/validate.py`) to update the matrix.

## Constraints honored

- **No mock data**: every endpoint returns either real data or a clear
  `not_implemented` 501.
- **LLM behind one class**: only `packages.llm` talks to a model.
- **robots.txt + rate limits**: each adapter throttles to the documented
  rate; `_base/http.py` honors `Retry-After`.
