"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Play, RefreshCcw, Sparkles, TrendingUp } from "lucide-react";
import { api, type RiskAssessment } from "@/lib/api";
import { MeshGradient } from "@/components/ui/mesh-gradient";
import { RiskScoreGauge } from "./RiskScoreGauge";

interface Props {
  country: string;
  identifier: string;
  companyName: string;
}

type Status = "idle" | "queued" | "running" | "done" | "error";

const STAGE_LABELS: Record<Status, string> = {
  idle: "Idle",
  queued: "Queueing risk job",
  running: "Calling Gemini · computing ratios · screening sanctions",
  done: "Complete",
  error: "Failed",
};

export function RiskAnalysisPanel({ country, identifier, companyName }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<RiskAssessment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  async function run() {
    setError(null);
    setResult(null);
    setStatus("queued");
    setElapsed(0);
    const startedAt = Date.now();
    const tickHandle = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 500);
    try {
      const { job_id } = await api.startRisk(country, identifier);
      setStatus("running");
      while (Date.now() - startedAt < 120_000) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await api.job(job_id);
        if (job.status === "done") {
          setResult(job.result as RiskAssessment);
          setStatus("done");
          return;
        }
        if (job.status === "error") {
          throw new Error(job.error || "Job failed");
        }
      }
      throw new Error("Timed out after 120s.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    } finally {
      clearInterval(tickHandle);
    }
  }

  const isWorking = status === "queued" || status === "running";

  return (
    <section className="space-y-5">
      {status === "idle" && (
        <EmptyHero companyName={companyName} onRun={run} />
      )}

      {isWorking && (
        <WorkingState stage={STAGE_LABELS[status]} elapsed={elapsed} />
      )}

      {status === "error" && (
        <div className="rounded-lg border border-danger/40 bg-danger/10 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 text-danger" />
            <div className="flex-1">
              <div className="font-semibold text-danger">Risk analysis failed</div>
              <div className="mt-1 text-sm text-danger/80">{error}</div>
            </div>
            <button
              onClick={run}
              className="rounded-md border border-danger/40 px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger/10"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {status === "done" && result && (
        <RiskResult result={result} onRerun={run} />
      )}
    </section>
  );
}

function EmptyHero({ companyName, onRun }: { companyName: string; onRun: () => void }) {
  return (
    <div className="relative isolate overflow-hidden rounded-lg border border-border-default bg-bg-elevated p-8">
      <MeshGradient intensity="normal" className="rounded-lg" />

      <div className="relative flex flex-col gap-5 md:flex-row md:items-center">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-brand-primary/15 text-brand-primary">
          <Sparkles className="h-7 w-7" />
        </div>
        <div className="flex-1">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-brand-primary">AI risk analysis</div>
          <h2 className="mt-1 font-display text-2xl font-semibold tracking-tight">
            Run a credit risk assessment on {companyName}
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-fg-muted">
            Deterministic ratios + filing context + sanctions screening, distilled into a score
            (0–100), recommended credit limit, key signals and red flags. Audit-ready.
          </p>
        </div>
        <button
          onClick={onRun}
          className="inline-flex items-center gap-2 self-start rounded-md bg-brand-primary px-4 py-2.5 text-sm font-semibold text-brand-primary-fg transition hover:bg-brand-primary/90 md:self-auto"
        >
          <Play className="h-4 w-4" /> Run analysis
        </button>
      </div>
    </div>
  );
}

function WorkingState({ stage, elapsed }: { stage: string; elapsed: number }) {
  return (
    <div className="overflow-hidden rounded-lg border border-brand-primary/30 bg-brand-primary/5 p-6">
      <div className="flex items-center gap-3">
        <DotTrailLoader />
        <div>
          <div className="text-sm font-semibold text-brand-primary">Analyzing</div>
          <div className="mt-0.5 text-xs text-fg-muted">{stage}</div>
        </div>
        <div className="ml-auto rounded-md bg-bg-base px-2.5 py-1 text-xs font-medium tabular-nums text-fg-muted">
          {elapsed}s
        </div>
      </div>
      <div className="relative mt-4 h-1 overflow-hidden rounded-full bg-bg-base">
        <motion.div
          className="absolute inset-y-0 w-1/3 rounded-full bg-gradient-to-r from-transparent via-brand-primary to-transparent"
          animate={{ x: ["-100%", "300%"] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>
      <div className="mt-3 text-xs text-fg-subtle">
        Typical analysis time: 5–25 seconds. Up to 2 minutes for companies with many years of filings.
      </div>
    </div>
  );
}

function DotTrailLoader() {
  return (
    <div className="flex h-5 items-center gap-1">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-2 w-2 rounded-full bg-brand-primary"
          animate={{ opacity: [0.25, 1, 0.25], scale: [0.8, 1.1, 0.8] }}
          transition={{
            duration: 1.1,
            repeat: Infinity,
            ease: "easeInOut",
            delay: i * 0.18,
          }}
        />
      ))}
    </div>
  );
}

function RiskResult({ result, onRerun }: { result: RiskAssessment; onRerun: () => void }) {
  const tone =
    result.recommendation === "APPROVE"
      ? "border-success/30 bg-success/5"
      : result.recommendation === "REVIEW"
        ? "border-warning/30 bg-warning/5"
        : "border-danger/30 bg-danger/5";

  return (
    <div className="space-y-5">
      <div className={`grid gap-5 rounded-lg border ${tone} p-6 md:grid-cols-[260px_1fr]`}>
        <div className="flex flex-col items-center justify-center border-b border-border-default pb-4 md:border-b-0 md:border-r md:pb-0 md:pr-6">
          <RiskScoreGauge
            score={result.score}
            recommendation={result.recommendation}
            confidence={result.confidence}
          />
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-xs font-medium uppercase tracking-[0.18em] text-fg-subtle">Recommended credit limit</div>
              <div className="mt-1 font-display text-3xl font-semibold tracking-tight">
                €{result.recommended_credit_limit_eur.toLocaleString("en-US", { maximumFractionDigits: 0 })}
              </div>
              <div className="mt-1 text-xs text-fg-muted">Calculated against deterministic ratios + filing context</div>
            </div>
            <button
              onClick={onRerun}
              className="rounded-md border border-border-default px-2.5 py-1.5 text-xs font-medium text-fg-muted transition hover:bg-bg-overlay"
            >
              <RefreshCcw className="mr-1 inline h-3 w-3" /> Rerun
            </button>
          </div>

          <div>
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-fg-subtle">Analyst summary</div>
            <p className="mt-2 text-sm leading-relaxed text-fg-default">{result.reasoning}</p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <SignalList
          title="Key signals"
          subtitle="What supports approving credit"
          icon={<CheckCircle2 className="h-4 w-4 text-success" />}
          items={result.key_signals}
          tone="positive"
        />
        <SignalList
          title="Red flags"
          subtitle="What suggests caution"
          icon={<AlertTriangle className="h-4 w-4 text-danger" />}
          items={result.red_flags}
          tone="negative"
        />
      </div>

      {result.ratios && result.ratios.length > 0 && (
        <RatiosTable rows={result.ratios} />
      )}

      <div className="text-[11px] text-fg-subtle">
        Model: <span className="font-mono">{result.model_used ?? "unknown"}</span>
      </div>
    </div>
  );
}

function SignalList({
  title,
  subtitle,
  icon,
  items,
  tone,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  items: string[];
  tone: "positive" | "negative";
}) {
  return (
    <div className="rounded-lg border border-border-default bg-bg-elevated p-4">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <div>
          <div className="text-sm font-semibold tracking-tight">{title}</div>
          <div className="text-[11px] text-fg-subtle">{subtitle}</div>
        </div>
        <span className="ml-auto rounded-md bg-bg-base px-1.5 py-0.5 text-[10px] text-fg-subtle">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border-default px-3 py-4 text-center text-xs text-fg-subtle">
          None identified.
        </div>
      ) : (
        <ul className="space-y-1.5">
          {items.map((s, i) => (
            <li
              key={i}
              className={
                "rounded-md border-l-2 px-3 py-2 text-sm " +
                (tone === "positive"
                  ? "border-success/60 bg-success/5 text-success"
                  : "border-danger/60 bg-danger/5 text-danger")
              }
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RatiosTable({ rows }: { rows: Array<Record<string, number | null | string>> }) {
  const periods = rows.map((r) => String(r.period ?? r.year ?? "—"));
  const sample = rows[rows.length - 1] ?? {};
  const metricKeys = Object.keys(sample).filter((k) => k !== "period" && k !== "year");

  return (
    <div className="overflow-hidden rounded-lg border border-border-default bg-bg-elevated">
      <div className="flex items-center gap-2 border-b border-border-default px-5 py-3">
        <TrendingUp className="h-4 w-4 text-brand-primary" />
        <div className="text-sm font-semibold tracking-tight">Deterministic ratios</div>
        <span className="ml-auto text-[11px] text-fg-subtle">
          Computed in-engine before the LLM ever sees the numbers
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-fg-muted">
              <th className="px-5 py-2 font-medium">Metric</th>
              {periods.map((p) => (
                <th key={p} className="px-5 py-2 text-right font-medium">{p}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((key) => (
              <tr key={key} className="border-t border-border-default">
                <td className="px-5 py-2 font-medium capitalize text-fg-default">{key.replace(/_/g, " ")}</td>
                {rows.map((r, i) => {
                  const v = r[key];
                  return (
                    <td key={i} className="px-5 py-2 text-right tabular-nums text-fg-muted">
                      {typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : v ?? "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
