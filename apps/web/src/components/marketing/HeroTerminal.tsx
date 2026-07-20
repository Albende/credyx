"use client";

import * as React from "react";

type Ratio = { k: string; v: string; good?: boolean };
type Demo = {
  cc: string;
  path: string;
  id: string;
  name: string;
  source: string;
  status: string;
  score: number;
  rec: "approve" | "review" | "reject";
  limit: string;
  ratios: Ratio[];
};

const DEMOS: Demo[] = [
  {
    cc: "CZ", path: "/companies/cz/00177041", id: "IČO 00177041",
    name: "Škoda Auto a.s.", source: "ARES", status: "active",
    score: 78, rec: "approve", limit: "€4.20M",
    ratios: [{ k: "Current", v: "1.42" }, { k: "D/E", v: "0.61" }, { k: "Altman-Z", v: "3.10", good: true }],
  },
  {
    cc: "FI", path: "/companies/fi/0112038-9", id: "Y-tunnus 0112038-9",
    name: "Nokia Oyj", source: "PRH", status: "active",
    score: 71, rec: "review", limit: "€3.10M",
    ratios: [{ k: "Current", v: "1.28" }, { k: "D/E", v: "0.74" }, { k: "Altman-Z", v: "2.60" }],
  },
  {
    cc: "SE", path: "/companies/se/5567037485", id: "Org.nr 556703-7485",
    name: "Spotify AB", source: "Bolagsverket", status: "active",
    score: 83, rec: "approve", limit: "€5.00M",
    ratios: [{ k: "Current", v: "1.61" }, { k: "D/E", v: "0.40" }, { k: "Altman-Z", v: "3.80", good: true }],
  },
];

const REC_TAG: Record<Demo["rec"], string> = {
  approve: "tag-good",
  review: "tag-warn",
  reject: "tag-bad",
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function HeroTerminal() {
  const [typed, setTyped] = React.useState("");
  const [status, setStatus] = React.useState<string | null>(null);
  const [demo, setDemo] = React.useState<Demo | null>(null);
  const [resolved, setResolved] = React.useState(false);
  const [visibleRatios, setVisibleRatios] = React.useState(0);
  const [score, setScore] = React.useState(0);
  const [recShown, setRecShown] = React.useState(false);
  const [log, setLog] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const pushLog = (line: string) =>
      setLog((l) => [...l.slice(-4), line]);

    async function run() {
      let i = 0;
      while (!cancelled) {
        const d = DEMOS[i % DEMOS.length];
        // reset
        setBusy(true); setTyped(""); setStatus(null); setDemo(d);
        setResolved(false); setVisibleRatios(0); setScore(0);
        setRecShown(false); setLog([]);
        await sleep(500); if (cancelled) return;

        // type request
        const req = `GET ${d.path}`;
        for (let c = 1; c <= req.length; c++) {
          if (cancelled) return;
          setTyped(req.slice(0, c));
          await sleep(26);
        }
        await sleep(280); if (cancelled) return;

        setStatus("200");
        pushLog(`→ resolving ${d.cc} registry…`);
        await sleep(560); if (cancelled) return;
        setResolved(true);
        pushLog(`✓ ${d.source}: ${d.name}`);
        await sleep(420); if (cancelled) return;

        pushLog("→ fetching filed financials…");
        await sleep(620); if (cancelled) return;
        pushLog("→ computing ratios (deterministic)…");
        await sleep(360); if (cancelled) return;
        for (let r = 1; r <= d.ratios.length; r++) {
          if (cancelled) return;
          setVisibleRatios(r);
          pushLog(`  ${d.ratios[r - 1].k} = ${d.ratios[r - 1].v}`);
          await sleep(300);
        }

        pushLog("→ scoring (model + ratios)…");
        await sleep(360); if (cancelled) return;
        // count up score
        const target = d.score;
        const steps = 26;
        for (let s = 1; s <= steps; s++) {
          if (cancelled) return;
          setScore(Math.round((target * s) / steps));
          await sleep(26);
        }
        setScore(target);
        setRecShown(true);
        pushLog(`✓ ${d.rec.toUpperCase()} · limit ${d.limit}`);
        setBusy(false);
        await sleep(2800); if (cancelled) return;
        i++;
      }
    }
    run();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="panel overflow-hidden">
      {/* request bar */}
      <div className="flex items-center justify-between gap-3 border-b border-border-default bg-bg-inset px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full border border-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full border border-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full border border-border-strong" />
        </div>
        <span className="truncate font-mono text-[0.7rem] text-fg-subtle">
          {typed}
          {busy && <span className="ml-px inline-block h-3 w-1.5 -translate-y-px animate-pulse bg-fg-subtle align-middle" />}
        </span>
        <span className={`font-mono text-[0.7rem] ${status === "200" ? "text-success" : "text-fg-subtle"}`}>
          {status ?? "···"}
        </span>
      </div>

      <div className="space-y-4 p-5">
        {/* company header */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-h-[3rem]">
            <div className="label">{demo ? `${demo.cc} · ${demo.id}` : "—"}</div>
            <div className={`mt-0.5 text-lg font-semibold tracking-tight transition-opacity duration-300 ${resolved ? "opacity-100" : "opacity-30"}`}>
              {demo?.name ?? "Resolving…"}
            </div>
            {resolved && demo && (
              <div className="mt-2 flex gap-1.5">
                <span className="badge tag-good">{demo.status}</span>
                <span className="badge">{demo.source}</span>
              </div>
            )}
          </div>
          {recShown && demo && (
            <span className={`badge ${REC_TAG[demo.rec]} shrink-0`}>● {demo.rec}</span>
          )}
        </div>

        {/* score */}
        <div className="rounded-md border border-border-default bg-bg-inset/60 p-4">
          <div className="flex items-center justify-between">
            <span className="label">Risk score</span>
            <span className="font-mono text-xs text-fg-subtle">
              {recShown && demo ? `limit ${demo.limit}` : "scoring…"}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="font-mono text-4xl font-semibold tabular-nums tracking-tight text-fg-default">
              {String(score).padStart(2, "0")}
            </span>
            <span className="font-mono text-sm text-fg-subtle">/ 100</span>
          </div>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-bg-overlay">
            <div
              className="h-full rounded-full bg-brand-primary transition-[width] duration-150 ease-out"
              style={{ width: `${score}%` }}
            />
          </div>
        </div>

        {/* ratios stream in */}
        <div className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-border-default bg-border-default">
          {(demo?.ratios ?? [{ k: "Current", v: "—" }, { k: "D/E", v: "—" }, { k: "Altman-Z", v: "—" }]).map((m, idx) => (
            <div key={m.k} className="bg-bg-elevated px-3 py-2.5">
              <div className="label">{m.k}</div>
              <div className={`mt-0.5 font-mono text-sm font-semibold tabular-nums transition-opacity duration-300 ${idx < visibleRatios ? "opacity-100" : "opacity-20"} ${m.good ? "text-success" : "text-fg-default"}`}>
                {idx < visibleRatios ? m.v : "—"}
              </div>
            </div>
          ))}
        </div>

        {/* streaming console */}
        <div className="flex h-[6.5rem] flex-col justify-end gap-0.5 overflow-hidden rounded-md border border-border-default bg-bg-inset px-3 py-2 font-mono text-[0.68rem] leading-snug text-fg-subtle">
          {log.map((line, i) => (
            <div key={i} className={line.startsWith("\u2713") ? "text-success" : ""}>{line}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
