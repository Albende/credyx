"use client";

import * as React from "react";

type Stat = { k: string; target: number; suffix?: string; decimals?: number; prefix?: string };

const FALLBACK: Stat[] = [
  { k: "Registries", target: 112 },
  { k: "Companies", target: 8.0, suffix: "M+", decimals: 1 },
  { k: "Sources", target: 35, suffix: "+" },
  { k: "Latency", target: 2, prefix: "<", suffix: "s" },
];

function useCountUp(target: number, run: boolean, decimals = 0, ms = 900) {
  const [val, setVal] = React.useState(0);
  React.useEffect(() => {
    if (!run) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else setVal(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, run, ms]);
  return decimals ? val.toFixed(decimals) : Math.round(val).toString();
}

function StatCell({ stat, run, index }: { stat: Stat; run: boolean; index: number }) {
  const shown = useCountUp(stat.target, run, stat.decimals ?? 0);
  return (
    <div className="px-4 py-4 first:pl-0">
      <div className="flex items-center gap-1.5 font-mono text-[0.62rem] uppercase tracking-[0.16em] text-fg-subtle">
        <span className="text-brand-primary">{String(index + 1).padStart(2, "0")}</span>
        {stat.k}
      </div>
      <dd className="mt-2 font-mono text-2xl font-semibold tabular-nums tracking-tight text-fg-default">
        {stat.prefix ?? ""}{shown}{stat.suffix ?? ""}
      </dd>
    </div>
  );
}

export function HeroStats() {
  const [stats, setStats] = React.useState<Stat[]>(FALLBACK);
  const [run, setRun] = React.useState(false);
  const ref = React.useRef<HTMLDListElement>(null);

  // start animation when in view
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setRun(true); io.disconnect(); } },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // pull the REAL live registry count from the backend
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/backend/countries", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const list: Array<{ capabilities?: { search?: boolean; lookup?: boolean } }> =
          data?.countries ?? [];
        const live = list.filter(
          (c) => c.capabilities?.search || c.capabilities?.lookup,
        ).length;
        if (!cancelled && live > 0) {
          setStats((prev) =>
            prev.map((s) => (s.k === "Registries" ? { ...s, target: live } : s)),
          );
        }
      } catch {
        /* keep fallback */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <dl
      ref={ref}
      className="mt-12 grid max-w-xl grid-cols-4 divide-x divide-border-default border-y border-border-default"
    >
      {stats.map((s, i) => (
        <StatCell key={s.k} stat={s} run={run} index={i} />
      ))}
    </dl>
  );
}
