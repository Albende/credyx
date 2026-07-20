"use client";
import { useState } from "react";
import { api, type CompanyDetails, type FinancialFiling, type RiskAssessment } from "@/lib/api";
import { FLAGS } from "@/lib/countries";

export default function CompanyView(props: {
  country: string;
  identifier: string;
  details: CompanyDetails;
  cached: boolean;
  filings: FinancialFiling[];
  financialsCached: boolean;
}) {
  const { country, identifier, details, filings } = props;

  return (
    <div className="space-y-6">
      <header className="card space-y-2">
        <div className="flex items-center gap-3">
          <span className="text-3xl">{FLAGS[country] || "🏳️"}</span>
          <div>
            <h1 className="text-2xl font-semibold">{details.name}</h1>
            <div className="text-xs text-muted">
              {details.identifiers.map((i) => `${i.label || i.type}: ${i.value}`).join(" · ")}
              {details.source_url ? (
                <>
                  {" · "}
                  <a href={details.source_url} target="_blank" rel="noreferrer" className="underline">
                    source
                  </a>
                </>
              ) : null}
            </div>
          </div>
          <div className="ml-auto flex gap-2">
            {details.status && (
              <span className={`badge ${details.status === "active" ? "tag-good" : "tag-warn"}`}>
                {details.status}
              </span>
            )}
            {props.cached && <span className="badge text-muted">cached</span>}
          </div>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2">
        <InfoCard
          title="Registry"
          rows={[
            ["Country", country],
            ["Legal form", details.legal_form],
            ["Status", details.status],
            ["Incorporated", details.incorporation_date],
            ["Address", details.registered_address],
            ["Capital", details.capital_amount && `${details.capital_amount} ${details.capital_currency || ""}`],
            ["SIC", details.sic_codes?.join(", ")],
            ["NACE", details.nace_codes?.join(", ")],
          ]}
        />
        <InfoCard
          title={`Directors / Officers (${details.directors?.length || 0})`}
          rows={(details.directors || []).slice(0, 8).map((d) => [
            d.name,
            [d.role, d.appointed_on].filter(Boolean).join(" · ") || null,
          ])}
          emptyText="No officer data available."
        />
      </section>

      <FinancialsBlock country={country} identifier={identifier} filings={filings} />

      <RiskCard country={country} identifier={identifier} />
    </div>
  );
}

function InfoCard({
  title,
  rows,
  emptyText,
}: {
  title: string;
  rows: [string, string | null | undefined | number][];
  emptyText?: string;
}) {
  const present = rows.filter(([_, v]) => v != null && v !== "");
  return (
    <div className="card">
      <h3 className="text-sm uppercase tracking-wider text-muted mb-3">{title}</h3>
      {present.length === 0 ? (
        <div className="text-sm text-muted">{emptyText || "No data."}</div>
      ) : (
        <dl className="space-y-2">
          {present.map(([k, v], i) => (
            <div key={i} className="flex gap-3">
              <dt className="text-sm text-muted w-32 shrink-0">{k}</dt>
              <dd className="text-sm">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function FinancialsBlock({
  country,
  identifier,
  filings,
}: {
  country: string;
  identifier: string;
  filings: FinancialFiling[];
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [current, setCurrent] = useState<FinancialFiling[]>(filings);

  async function refresh() {
    setRefreshing(true);
    try {
      const data = await api.financials(country, identifier, { force: true });
      setCurrent(data.filings);
    } catch (e) {
      // noop — surface via empty state
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <section className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm uppercase tracking-wider text-muted">
          Financial filings ({current.length})
        </h3>
        <button className="btn" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      {current.length === 0 ? (
        <div className="text-sm text-muted">
          No filings retrieved. Either the country adapter doesn't yet implement
          financials, or the source returned none. Click <em>Refresh</em> to retry.
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {current.map((f, i) => (
            <li key={i} className="py-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{f.year}</span>
                <span className="badge">{f.type}</span>
                {f.currency && <span className="text-muted">{f.currency}</span>}
                {f.period_end && <span className="text-muted">period end {f.period_end}</span>}
                <div className="ml-auto flex gap-2">
                  {f.document_url && (
                    <a href={f.document_url} target="_blank" rel="noreferrer" className="btn">
                      {f.document_format === "pdf" ? "Download PDF" : "View document"}
                    </a>
                  )}
                  {f.source_url && (
                    <a href={f.source_url} target="_blank" rel="noreferrer" className="btn">
                      Source
                    </a>
                  )}
                </div>
              </div>
              {f.structured_data && (
                <details className="mt-2 text-xs text-muted">
                  <summary className="cursor-pointer">Structured data</summary>
                  <pre className="mt-2 overflow-x-auto rounded bg-bg-inset p-2">
                    {JSON.stringify(f.structured_data, null, 2)}
                  </pre>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RiskCard({ country, identifier }: { country: string; identifier: string }) {
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [result, setResult] = useState<RiskAssessment | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setError(null);
    setResult(null);
    setStatus("running");
    try {
      const { job_id } = await api.startRisk(country, identifier);
      // Poll up to 60s.
      const started = Date.now();
      while (Date.now() - started < 90_000) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await api.job(job_id);
        if (job.status === "done") {
          setResult(job.result as RiskAssessment);
          setStatus("done");
          return;
        }
        if (job.status === "error") {
          throw new Error(job.error || "job failed");
        }
      }
      throw new Error("Timed out after 90s.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  }

  return (
    <section className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm uppercase tracking-wider text-muted">AI credit risk analysis</h3>
        <button onClick={start} disabled={status === "running"} className="btn btn-primary">
          {status === "running" ? "Running..." : "Run analysis"}
        </button>
      </div>

      {error && <div className="text-bad text-sm">Error: {error}</div>}
      {status === "running" && (
        <div className="text-sm text-muted">
          Calling Gemini via kie.ai. This takes 5–25 seconds depending on data volume.
        </div>
      )}
      {result && <RiskResult r={result} />}
    </section>
  );
}

function RiskResult({ r }: { r: RiskAssessment }) {
  const cls = r.recommendation === "APPROVE" ? "tag-good" : r.recommendation === "REVIEW" ? "tag-warn" : "tag-bad";
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase tracking-wider text-muted">Score</div>
          <div className="text-3xl font-semibold mt-1">{r.score}<span className="text-muted text-base"> /100</span></div>
          <div className="text-xs text-muted">confidence {(r.confidence * 100).toFixed(0)}%</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wider text-muted">Recommendation</div>
          <div className={`mt-1 inline-flex rounded-md px-2.5 py-1 text-sm font-medium border ${cls}`}>
            {r.recommendation}
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wider text-muted">Recommended credit limit</div>
          <div className="text-3xl font-semibold mt-1">
            €{r.recommended_credit_limit_eur.toLocaleString("en-US", { maximumFractionDigits: 0 })}
          </div>
        </div>
      </div>
      <p className="text-sm leading-relaxed">{r.reasoning}</p>
      <div className="grid gap-3 md:grid-cols-2">
        <SignalList title="Key signals" items={r.key_signals} good />
        <SignalList title="Red flags" items={r.red_flags} />
      </div>
      <div className="text-xs text-muted">Model: {r.model_used || "unknown"}</div>
    </div>
  );
}

function SignalList({ title, items, good }: { title: string; items: string[]; good?: boolean }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wider text-muted mb-2">{title}</div>
      {items.length === 0 ? (
        <div className="text-sm text-muted">None.</div>
      ) : (
        <ul className="text-sm space-y-1 list-disc pl-5">
          {items.map((s, i) => (
            <li key={i} className={good ? "text-good" : "text-bad"}>
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
