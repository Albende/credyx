# CreditLens

B2B credit intelligence platform. Pulls **real** company data from official
government registries across Europe, Türkiye, and the USA, then runs an
AI-powered credit risk analysis via **Gemini (kie.ai)**.

No commercial paid APIs. No mock data. Every endpoint returns real source
data or a clear `not_implemented` 501 — adapters are honest about coverage.

---

## Quick start

```bash
git clone <this-repo> creditlens
cd creditlens
cp .env.example .env          # then fill in keys you have
docker compose up --build
```

- Frontend: <http://localhost:3000>
- API:      <http://localhost:8000>
- API docs: <http://localhost:8000/docs>
- pgAdmin:  <http://localhost:5050> (admin@creditlens.local / admin)

The first request to `/api/countries` triggers health probes for every
adapter, so the homepage automatically reflects which countries are live,
need a key, or are still stubbed.

---

## Coverage status (live)

The Coverage page (`/coverage`) is auto-generated from `/api/countries`,
which runs each adapter's `health_check()`. Snapshot below — see live page
for current state.

| Country | Adapter | Search | Lookup | Financials | Notes |
|---------|---------|:------:|:------:|:----------:|-------|
| 🇬🇧 GB | Companies House REST | ✅ | ✅ | ✅ (PDF URLs) | Needs `UK_COMPANIES_HOUSE_API_KEY` |
| 🇺🇸 US | SEC EDGAR | ✅ | ✅ | ✅ (XBRL) | SEC-registered only |
| 🇫🇷 FR | recherche-entreprises.api.gouv.fr | ✅ | ✅ | 🟡 | Financials via INPI OAuth (not wired) |
| 🇳🇱 NL | KvK Handelsregister | ✅ | ✅ | 🟡 | Needs `NL_KVK_API_KEY` |
| 🇨🇿 CZ | ARES | ✅ | ✅ | 🟡 | Filings via Sbírka listin (PDFs) |
| 🇪🇪 EE | Äriregister | 🟡 | 🟡 | — | Live API needs paid contract |
| 🇳🇴 NO | Brønnøysund | ✅ | ✅ | 🟡 | Regnskapsregisteret PDFs not wired |
| 🇫🇮 FI | PRH YTJ | ✅ | ✅ | 🟡 | Financials are PRH paid service |
| 🇩🇪 DE, 🇵🇱 PL, 🇪🇸 ES, 🇮🇹 IT, 🇧🇪 BE, 🇸🇪 SE, 🇩🇰 DK, 🇮🇪 IE, 🇦🇹 AT, 🇸🇰 SK, 🇭🇺 HU, 🇷🇴 RO, 🇧🇬 BG, 🇭🇷 HR, 🇸🇮 SI, 🇱🇹 LT, 🇱🇻 LV, 🇵🇹 PT, 🇱🇺 LU, 🇲🇹 MT, 🇨🇾 CY, 🇬🇷 GR, 🇹🇷 TR | Stub | — | — | — | See `docs/countries/{cc}.md` |

Plus globals: GLEIF, OpenCorporates, OpenSanctions.

---

## Configuration

Copy `.env.example` to `.env`. Keys you need:

| Variable | Required for | Where to get |
|----------|--------------|--------------|
| `KIE_AI_API_KEY` | Risk analysis (every country) | <https://kie.ai/> |
| `UK_COMPANIES_HOUSE_API_KEY` | UK adapter | <https://developer.company-information.service.gov.uk/get-started> |
| `NL_KVK_API_KEY` | NL adapter | <https://developers.kvk.nl/> |
| `OPENCORPORATES_API_KEY` | OpenCorporates lookups | <https://opencorporates.com/api_accounts/new> |
| `SEC_EDGAR_USER_AGENT` | US adapter (recommended) | Your contact email |

Without `KIE_AI_API_KEY`, all endpoints work **except** the risk analysis,
which raises a clear error.

---

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full diagram.
Short version:

- **`apps/web`** — Next.js 15 + Tailwind. Country picker → search → company
  detail → "Run AI credit analysis" button.
- **`apps/api`** — FastAPI. Adapter registry, rate limiting, jobs, caching.
- **`packages/adapters/{cc}`** — Per-country plug-ins. All share the
  `CountryAdapter` ABC.
- **`packages/llm`** — The only place that talks to a model
  (`KieAIGeminiProvider`). Behind `LLMService` so providers can swap.
- **`packages/risk`** — Computes financial ratios deterministically; the LLM
  never does arithmetic.
- **`packages/shared/models.py`** — Pydantic v2 contract used everywhere.
- **Postgres** — caches registry data (7d) and filings (30d), stores risk
  history and ingestion jobs.
- **Redis** — IP rate limiting (60/min default).

---

## Adding a new country adapter (one-page guide)

1. Create `packages/adapters/{cc}/adapter.py`.
2. Subclass `CountryAdapter`:

   ```python
   class XYAdapter(CountryAdapter):
       country_code = "XY"
       country_name = "Xanadu"
       identifier_types = [IdentifierType.OTHER]
       primary_identifier = IdentifierType.OTHER

       async def search_by_name(self, name: str, limit: int = 10): ...
       async def lookup_by_identifier(self, id_type, value): ...
       async def fetch_financials(self, company_id: str, years: int = 5): ...
   ```

3. Register it in `packages/adapters/registry.py` → `_build_real_adapters`.
4. Write at least one integration test in `packages/adapters/{cc}/tests/`
   marked `@pytest.mark.integration`. **Tests hit the real source** — skip
   in CI if creds/network missing, but never mock.
5. Add `docs/countries/{cc}.md` with the research findings.
6. Run `python scripts/validate.py` to refresh `docs/VALIDATION_REPORT.md`.

---

## Running validation

```bash
python scripts/validate.py
```

Pings every adapter with one of the canonical test companies from the spec,
records pass/fail per step (search → lookup → financials → risk analysis),
and writes a matrix to `docs/VALIDATION_REPORT.md`.

---

## Tests

```bash
# unit + integration (integration tests skip if creds missing)
pip install -r apps/api/requirements.txt
pip install pytest pytest-asyncio pytest-httpx
PYTHONPATH=. pytest packages/adapters
```

---

## Costs (rough, per 1000 lookups/day)

| Item | Estimate |
|------|----------|
| Postgres + Redis (single-node) | $20–40/mo |
| Gemini Flash via kie.ai (~3K input + ~500 output tokens × 1000) | $5–15/mo |
| Proxy rotation (if/when scrapers added) | $50–200/mo |
| Hosting (small VPS or Fly.io) | $20–50/mo |
| **Total** | **~$100–300/mo at 1k/day** |

---

## License & Compliance notes

- Government registry data is generally open or freely accessible per ToS,
  but **commercial use varies by country**. Check
  `docs/countries/{cc}.md` for per-country notes.
- OpenSanctions API is free for non-commercial only — a license is required
  for commercial sanctions screening.
- OpenCorporates free tier is for personal/non-commercial; commercial use
  requires a paid plan.

---

## Status, in one sentence

A working FastAPI + Next.js stack with **8 live country adapters**
(UK / US / FR / NL / CZ / EE / NO / FI) hitting real government APIs, plus
**23 stub adapters** that surface clear `not_implemented` errors and link
to documented next steps — and a Gemini-powered credit risk engine wired
end-to-end through deterministic financial ratios.
