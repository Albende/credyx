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

## ESEF / iXBRL parsing

`packages/risk/xbrl_esef.py` extracts structured financial data from
European Single Electronic Format filings — the EU-mandated iXBRL
taxonomy for listed companies' annual reports since 2021.

- **Inputs**: raw XHTML/XML bytes or a ZIP package (the standard ESEF
  distribution shape). The parser auto-detects the ZIP magic and pulls
  the iXBRL document out of `reports/`.
- **Output**: a `structured_data` dict matching the shape
  `packages/risk/ratios.py` already consumes, so ratios slot in for free.
- **Concepts mapped**: 22 IFRS Foundation `ifrs-full:*` concepts covering
  the balance sheet, income statement, and cash-flow statement. The map
  accepts any IFRS taxonomy year (2022 / 2023 / 2024) via a namespace
  regex.
- **Numeric handling**: honors iXBRL `scale`, `sign`, and parenthesised
  negatives; supports US (`1,234,567.89`) and European (`1.234.567,89`)
  decimal styles seen in real filings.
- **Period selection**: picks the latest reporting end-date and unifies
  the instant (balance sheet) + duration (income statement) contexts that
  share that date.
- **Consolidated detection**: scans context `explicitMember` segments for
  `Separate`/`Parent` axes; defaults to consolidated.
- **Stdlib-only**: `xml.etree.ElementTree`, `zipfile`, `io` — no `arelle`
  (it's ~100MB) and no new third-party deps.
- **Failure mode**: raises `XBRLParseError` with context; never returns
  fabricated values.

Call from an adapter:

```python
from packages.risk import parse_esef_url
structured = await parse_esef_url(filing_url, http_client=client)
filing.structured_data = structured
```

## Browser pool (`packages/adapters/_base/browser.py`)

Many registries cannot be reached with plain httpx because they ship a
JS-rendered SPA, require a ViewState handshake, or wait for an XHR
before rendering the result table. The browser pool is a process-wide
`BrowserPool` that keeps a single Chromium process and a small queue of
hot `BrowserContext` instances ready to serve adapter requests.

### Usage in an adapter

```python
from packages.adapters._base.browser import get_browser_pool

pool = get_browser_pool()
async with pool.acquire(locale="es-ES") as ctx:
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.fill("input[name=rut]", rut)
        await page.click("button[type=submit]")
        await page.wait_for_selector("#result-table tr")
        html = await page.content()
    finally:
        await page.close()
```

Rules:

- Always borrow with `async with` so the context is returned to the pool
  even on exception. A poisoned context is auto-replaced.
- Cookies and pages are wiped between borrowers by default. Pass
  `persistent_id="dk-virk"` to keep the same context for a session that
  needs sign-in / cached storage.
- If the page renders a CAPTCHA, raise `BlockedByRegistryError`. The
  pool does not solve them, and the project does not integrate paid
  solvers.
- The pool starts lazily on the first `acquire()`. Call
  `await close_browser_pool()` on FastAPI shutdown.

### Configuration (env)

| Variable                    | Default     | Meaning                                  |
|-----------------------------|-------------|------------------------------------------|
| `BROWSER_POOL_SIZE`         | 5           | Number of hot contexts kept warm         |
| `BROWSER_HEADLESS`          | true        | Set `false` to debug locally with a UI   |
| `PROXY_SERVER`              | unset       | When set, browser traffic routes through |
| `PROXY_USER` / `PROXY_PASS` | unset       | Optional proxy credentials               |
| `PROXY_ROTATION`            | per_request | `per_request` or `per_session`           |

Install Chromium once (after `pip install -r apps/api/requirements.txt`):

```bash
make install-browsers           # or: python -m playwright install chromium
```

### Proxy interface (`packages/adapters/_base/proxy.py`)

`ProxyProvider` is a tiny ABC with one method, `get_proxy()`. The MVP
ships `NoopProxyProvider` (default; no proxy) and `EnvProxyProvider`
(reads `PROXY_SERVER` / `PROXY_USER` / `PROXY_PASS`). Paid rotating-IP
providers (Bright Data, Oxylabs, etc.) plug in by subclassing
`ProxyProvider` and registering via `set_proxy_provider()`. The pool
consults the provider once per Chromium launch; per-request rotation is
a Phase-2 enhancement that swaps contexts instead of relaunching.

### Wiring another adapter onto the pool

1. Confirm the registry needs JS rendering. If a plain httpx GET returns
   the data, use httpx; the pool exists for SPAs and multi-step form
   sessions.
2. Replace the offending method body with a `pool.acquire()` block:
   ```python
   from packages.adapters._base.browser import get_browser_pool
   pool = get_browser_pool()
   async with pool.acquire(locale="<best-locale>") as ctx:
       page = await ctx.new_page()
       ...
   ```
3. If the registry shows a CAPTCHA, raise
   `BlockedByRegistryError("registry X gates with CAPTCHA")` — do NOT
   try to solve it.
4. Keep deterministic HTML extraction in pure functions so they stay
   unit-testable without spawning a browser (see `packages/adapters/ge`
   for the pattern — `_extract_search_results`, `_extract_company_record`
   are pure).
5. Add an `@pytest.mark.integration` test that drives the real adapter
   end-to-end. Unit tests should install a fake `playwright.async_api`
   module (see `packages/adapters/_base/tests/test_browser.py` for the
   stub shape) when verifying pool semantics without Chromium.

### Demo adapter: GE (Georgia) NAPR

`packages/adapters/ge/adapter.py` was the first adapter rewired onto the
pool. NAPR's `show_legal_person_form` endpoint returns an empty
`#search_result` shell and populates it via XHR, so the previous httpx
path could only see zero results for name searches. The new
`_render_search_page()` opens the form in a pooled context, fills the
`s_legal_person_name` input, clicks submit, waits for the results
selector, and returns the post-render HTML to the existing pure
extractors. Direct ID lookup still uses httpx because that endpoint
server-renders.
