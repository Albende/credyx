import type { Metadata } from "next";
import Link from "next/link";

const TITLE = "API Reference — Credyx";
const DESCRIPTION =
  "REST API reference for Credyx: company search, registry lookups, financial filings, risk analysis and sanctions screening.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    images: ["/og/og-home.png"],
  },
};

type Param = { name: string; type: string; desc: string };

type Endpoint = {
  method: "GET" | "POST";
  path: string;
  title: string;
  desc: string;
  params?: Param[];
  paramsLabel?: string;
  example: string;
  exampleLabel?: string;
};

const ENDPOINTS: Endpoint[] = [
  {
    method: "GET",
    path: "/api/countries",
    title: "List supported countries",
    desc: "Returns every country adapter with its capabilities and status. Static metadata by default (fast); pass probe=true to run live health checks against each registry (~30s).",
    params: [
      {
        name: "probe",
        type: "boolean, default false",
        desc: "Run live health probes against every adapter instead of returning static metadata.",
      },
    ],
    example: `{
  "countries": [
    {
      "country_code": "gb",
      "name": "United Kingdom",
      "status": "ok",
      "capabilities": { "search": true, "lookup": true, "financials": true },
      "requires_api_key": true,
      "api_key_present": true,
      "rate_limit_per_minute": 600,
      "notes": null
    }
  ]
}`,
  },
  {
    method: "GET",
    path: "/api/search",
    title: "Search companies by name",
    desc: "Name search within one country via the national registry adapter. If the adapter has no name search (or returns nothing) and fallback is enabled, results come from GLEIF instead — the source field tells you which. Returns 501 when the adapter is not implemented and the fallback found nothing.",
    params: [
      { name: "country", type: "string, required", desc: "ISO 3166-1 alpha-2 country code, e.g. gb, us, fr." },
      { name: "name", type: "string, required", desc: "Company name query, minimum 2 characters." },
      { name: "limit", type: "integer, 1–50, default 10", desc: "Maximum number of matches." },
      { name: "fallback", type: "boolean, default true", desc: "Fall back to GLEIF when the national adapter has no name search." },
    ],
    example: `{
  "country": "GB",
  "query": "acme",
  "source": "adapter",
  "results": [
    {
      "id": "01234567",
      "name": "ACME TRADING LIMITED",
      "country": "GB",
      "identifiers": [
        { "type": "COMPANY_NUMBER", "value": "01234567", "label": null }
      ],
      "address": "1 Poultry, London EC2R 8EJ",
      "status": "active",
      "source_url": "https://find-and-update.company-information.service.gov.uk/company/01234567"
    }
  ]
}`,
  },
  {
    method: "GET",
    path: "/api/search/global",
    title: "Global search (GLEIF)",
    desc: "Name search across GLEIF's LEI database without a country filter — roughly 2M+ legal entities worldwide. Useful when you don't know where a counterparty is registered.",
    params: [
      { name: "name", type: "string, required", desc: "Company name query, minimum 2 characters." },
      { name: "limit", type: "integer, 1–50, default 10", desc: "Maximum number of matches." },
    ],
    example: `{
  "query": "acme",
  "source": "gleif",
  "results": [ /* same CompanyMatch shape as /api/search */ ]
}`,
  },
  {
    method: "GET",
    path: "/api/companies/{country}/{identifier}",
    title: "Company lookup",
    desc: "Full registry record for one company. Served from the Postgres cache when fresh (7-day TTL); otherwise fetched live from the registry. If the identifier is a 20-character LEI, the lookup is resolved via GLEIF regardless of country.",
    params: [
      { name: "id_type", type: "string, optional", desc: "Override the identifier type (COMPANY_NUMBER, SIREN, KRS, ICO, CIK, …). Defaults to the adapter's primary identifier." },
      { name: "force_refresh", type: "boolean, default false", desc: "Bypass the cache and fetch from the registry." },
    ],
    example: `{
  "cached": true,
  "last_fetched_at": "2026-07-18T09:12:44Z",
  "details": {
    "id": "01234567",
    "name": "ACME TRADING LIMITED",
    "country": "GB",
    "legal_form": "ltd",
    "status": "active",
    "incorporation_date": "2004-03-19",
    "registered_address": "1 Poultry, London EC2R 8EJ",
    "sic_codes": ["46190"],
    "identifiers": [
      { "type": "COMPANY_NUMBER", "value": "01234567", "label": null }
    ],
    "directors": [
      { "name": "Jane Doe", "role": "director", "appointed_on": "2019-01-04" }
    ],
    "source_url": "https://find-and-update.company-information.service.gov.uk/company/01234567"
  }
}`,
  },
  {
    method: "GET",
    path: "/api/companies/{country}/{identifier}/financials",
    title: "Financial filings",
    desc: "Filed balance sheets and annual reports for a company, newest first. Cached for 30 days. With with_text=true, PDF filings are downloaded and their text extracted into structured_data.pdf_text_excerpts (slow; requires a plan with the pdf_extraction feature, otherwise 403).",
    params: [
      { name: "years", type: "integer, 1–20, default 5", desc: "How many filing years to fetch." },
      { name: "force_refresh", type: "boolean, default false", desc: "Bypass the 30-day filings cache." },
      { name: "with_text", type: "boolean, default false", desc: "Extract text from PDF filings. Plan-gated." },
    ],
    example: `{
  "country": "GB",
  "company_id": "0d4f6c1e-8f2a-4a51-9c1b-3e7a2f0b9d10",
  "cached": false,
  "filings": [
    {
      "year": 2025,
      "type": "annual_report",
      "period_end": "2025-03-31",
      "currency": "GBP",
      "structured_data": { "total_assets": 1830450, "equity": 612300 },
      "document_url": "https://find-and-update.company-information.service.gov.uk/.../document",
      "document_format": "pdf",
      "source_url": "https://find-and-update.company-information.service.gov.uk/company/01234567/filing-history"
    }
  ]
}`,
  },
  {
    method: "POST",
    path: "/api/companies/{country}/{identifier}/risk-analysis",
    title: "Start a risk analysis",
    desc: "Kicks off an asynchronous credit risk assessment: filings are loaded (fetched if missing), deterministic ratios are computed in code, sanctions screening runs, and the LLM produces the structured verdict. Returns a job id immediately — poll /api/jobs/{job_id} for the result. Requires a plan with the risk_analysis feature.",
    example: `{
  "job_id": "7f2b9c34-51de-4a0f-9e6d-2c8b1a7f4e55",
  "status": "queued"
}`,
  },
  {
    method: "GET",
    path: "/api/jobs/{job_id}",
    title: "Poll a job",
    desc: "Status of an asynchronous job. status moves through queued → running → done (or error). For risk analysis jobs, result contains the full RiskAssessment once done. Assessments are persisted permanently for audit.",
    example: `{
  "job_id": "7f2b9c34-51de-4a0f-9e6d-2c8b1a7f4e55",
  "kind": "risk_analysis",
  "status": "done",
  "result": {
    "score": 71,
    "recommendation": "APPROVE",
    "recommended_credit_limit_eur": 50000,
    "reasoning": "Stable revenue, conservative leverage; monitor the fall in quick ratio.",
    "key_signals": ["current_ratio 1.8", "positive equity trend 3y"],
    "red_flags": [],
    "confidence": 0.82,
    "ratios": [
      { "year": 2025, "current_ratio": 1.8, "debt_to_equity": 0.6, "altman_z": 3.1 }
    ],
    "model_used": "gemini-2.5-pro"
  },
  "error": null
}`,
  },
  {
    method: "POST",
    path: "/api/screen",
    title: "Sanctions screening",
    desc: "Ad-hoc OpenSanctions screening of a company or person, independent of any lookup. The risk engine also screens automatically on every risk analysis run.",
    paramsLabel: "Request body",
    params: [
      { name: "name", type: "string, required", desc: "Entity name to screen." },
      { name: "country", type: "string, optional", desc: "ISO country code to narrow matching." },
      { name: "identifiers", type: "string[], optional", desc: "Registration numbers, LEIs, tax ids." },
      { name: "schema", type: "string, default \"Company\"", desc: "OpenSanctions schema: Company, Person, …" },
      { name: "limit", type: "integer, 1–25, default 5", desc: "Maximum hits returned." },
    ],
    example: `[
  {
    "entity_id": "NK-4bT...",
    "caption": "ACME HOLDINGS LLC",
    "schema": "Company",
    "score": 0.87,
    "datasets": ["us_ofac_sdn"],
    "topics": ["sanction"]
  }
]`,
  },
  {
    method: "GET",
    path: "/api/healthz",
    title: "Health check",
    desc: "Liveness probe. No authentication required.",
    example: `{ "status": "ok" }`,
  },
];

const ERRORS: { code: string; meaning: string }[] = [
  { code: "400", meaning: "Invalid identifier or unknown id_type for the country." },
  { code: "401", meaning: "Missing, expired, or revoked bearer token." },
  { code: "403", meaning: "Feature not in your plan (e.g. risk_analysis, pdf_extraction). The body includes an upgrade_url." },
  { code: "404", meaning: "No adapter for the country, or company/job not found." },
  { code: "429", meaning: "Plan quota exceeded (searches/day, lookups/day, financials/month, risk analyses/month) or rate limit hit." },
  { code: "501", meaning: "The country adapter cannot return real data yet. Credyx never substitutes mock data — a 501 is the honest answer." },
];

function MethodBadge({ method }: { method: Endpoint["method"] }) {
  const tone =
    method === "GET"
      ? "border-success/30 bg-success/10 text-success"
      : "border-accent/30 bg-accent/10 text-accent";
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[0.68rem] font-semibold uppercase tracking-wide ${tone}`}
    >
      {method}
    </span>
  );
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div className="mt-5">
      <p className="serial">{label}</p>
      <pre className="mt-2 overflow-x-auto rounded-lg border border-border-default bg-bg-inset p-4 font-mono text-xs leading-relaxed text-fg-default">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function ApiReferencePage() {
  return (
    <>
      <section className="border-b border-border-default pb-16 pt-24">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <p className="serial">Resources</p>
            <h1 className="mt-3 font-display text-display-xl tracking-tight">
              API reference
            </h1>
            <p className="mt-6 text-lg leading-relaxed text-fg-muted">
              Everything the Credyx dashboard does, your systems can do over REST:
              search official registries, pull full company records and filed
              financials, and run asynchronous credit risk assessments. All
              responses are JSON.
            </p>
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-16">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <h2 className="font-display text-2xl tracking-tight">
              Base URL and authentication
            </h2>
            <p className="mt-4 text-[0.95rem] leading-relaxed text-fg-muted">
              All endpoints live under <code className="font-mono text-[0.85em] text-fg-default">/api</code>.
              Authenticate with a bearer token in the{" "}
              <code className="font-mono text-[0.85em] text-fg-default">Authorization</code>{" "}
              header — create and manage keys under{" "}
              <Link
                href="/app/account/api-keys"
                className="font-medium text-brand-primary underline-offset-4 hover:underline"
              >
                Account &rarr; API keys
              </Link>
              . Endpoints marked plan-gated require the corresponding feature in
              your{" "}
              <Link
                href="/pricing"
                className="font-medium text-brand-primary underline-offset-4 hover:underline"
              >
                subscription plan
              </Link>
              .
            </p>
            <pre className="mt-5 overflow-x-auto rounded-lg border border-border-default bg-bg-inset p-4 font-mono text-xs leading-relaxed text-fg-default">
              <code>{`curl https://api.credyx.ai/api/search?country=gb&name=acme \\
  -H "Authorization: Bearer $CREDYX_API_KEY"`}</code>
            </pre>

            <h2 className="mt-12 font-display text-2xl tracking-tight">
              Caching and freshness
            </h2>
            <p className="mt-4 text-[0.95rem] leading-relaxed text-fg-muted">
              Registry records are cached for 7 days and filings for 30 days;
              responses carry a{" "}
              <code className="font-mono text-[0.85em] text-fg-default">cached</code>{" "}
              flag and, where applicable, a{" "}
              <code className="font-mono text-[0.85em] text-fg-default">last_fetched_at</code>{" "}
              timestamp. Every fetch endpoint accepts{" "}
              <code className="font-mono text-[0.85em] text-fg-default">force_refresh=true</code>{" "}
              to go straight to the source. Risk assessments are never evicted —
              they form your audit trail.
            </p>

            <h2 className="mt-12 font-display text-2xl tracking-tight">Errors</h2>
            <div className="mt-5 overflow-x-auto rounded-lg border border-border-default">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border-default bg-bg-elevated">
                    <th className="px-4 py-2.5 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-fg-subtle">
                      Status
                    </th>
                    <th className="px-4 py-2.5 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-fg-subtle">
                      Meaning
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ERRORS.map((e) => (
                    <tr key={e.code} className="border-b border-border-default last:border-b-0">
                      <td className="px-4 py-2.5 font-mono text-xs font-semibold text-fg-default">
                        {e.code}
                      </td>
                      <td className="px-4 py-2.5 text-fg-muted">{e.meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-16">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <h2 className="font-display text-display-lg tracking-tight">Endpoints</h2>
            <div className="mt-10 space-y-8">
              {ENDPOINTS.map((ep) => (
                <article
                  key={`${ep.method} ${ep.path}`}
                  className="plate rounded-xl border border-border-default bg-bg-elevated p-6 shadow-elev-1 md:p-8"
                >
                  <div className="flex flex-wrap items-center gap-2.5">
                    <MethodBadge method={ep.method} />
                    <code className="break-all font-mono text-sm font-medium text-fg-default">
                      {ep.path}
                    </code>
                  </div>
                  <h3 className="mt-4 text-base font-semibold tracking-tight">
                    {ep.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-fg-muted">{ep.desc}</p>

                  {ep.params && (
                    <div className="mt-5">
                      <p className="serial">{ep.paramsLabel ?? "Query parameters"}</p>
                      <ul className="mt-2 space-y-2 text-sm">
                        {ep.params.map((p) => (
                          <li key={p.name} className="text-fg-muted">
                            <code className="font-mono text-xs font-semibold text-fg-default">
                              {p.name}
                            </code>{" "}
                            <span className="text-fg-subtle">({p.type})</span> — {p.desc}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <CodeBlock label={ep.exampleLabel ?? "Example response"} code={ep.example} />
                </article>
              ))}
            </div>

            <p className="mt-12 text-sm leading-relaxed text-fg-muted">
              Live interactive OpenAPI docs (Swagger) are served by the API itself at{" "}
              <code className="font-mono text-[0.85em] text-fg-default">/docs</code>{" "}
              on your API host. Questions or missing endpoints:{" "}
              <a
                href="mailto:support@credyx.ai"
                className="font-medium text-brand-primary underline-offset-4 hover:underline"
              >
                support@credyx.ai
              </a>
              .
            </p>
          </div>
        </div>
      </section>
    </>
  );
}
