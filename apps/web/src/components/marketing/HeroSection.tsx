"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, PlayCircle, ShieldCheck, TrendingUp, Activity } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BadgeLive } from "@/components/ui/badge-live";
import { AuroraText } from "@/components/ui/aurora-text";
import { MeshGradient } from "@/components/ui/mesh-gradient";
import { Grain } from "@/components/ui/grain";
import { Sparkline } from "@/components/ui/sparkline";
import { spring, outExpo } from "@/lib/motion";

const PREVIEW_LOGOS = ["Companies House", "SEC EDGAR", "INSEE Sirene"];

const SPARK_A = [42, 48, 45, 53, 58, 56, 64, 71, 69, 78, 84, 82];
const SPARK_B = [70, 65, 68, 60, 62, 55, 52, 48, 50, 44, 42, 40];
const SPARK_C = [12, 15, 14, 18, 22, 21, 26, 30, 34, 33, 39, 44];

export function HeroSection() {
  return (
    <section className="relative isolate flex min-h-[calc(100vh-4rem)] items-center overflow-hidden">
      <MeshGradient intensity="normal" />
      <Grain className="opacity-20" />

      {/* Engraved guilloché band — the security-print signature */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[65%] [mask-image:linear-gradient(to_bottom,black,transparent)]"
      >
        <div className="texture-guilloche absolute inset-0 text-brand-primary/[0.09]" />
      </div>

      {/* Fine grid wash for instrument feel */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-grid bg-[length:48px_48px] opacity-[0.05] [mask-image:radial-gradient(70%_60%_at_50%_30%,black,transparent)]"
      />

      <div className="container relative grid items-center gap-x-14 gap-y-16 py-20 md:py-24 lg:grid-cols-[1.08fr_0.92fr] lg:py-28">
        {/* Left — editorial */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: outExpo }}
          className="max-w-2xl"
        >
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: outExpo }}
          >
            <BadgeLive label="Live — 112 country adapters" />
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.75, ease: outExpo, delay: 0.05 }}
            className="mt-6 font-display text-6xl font-semibold tracking-[-0.035em] text-fg-default text-balance sm:text-7xl"
          >
            Underwrite any company on the{" "}
            <AuroraText>primary</AuroraText> record.
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: outExpo, delay: 0.12 }}
            className="mt-6 max-w-prose text-[18px] leading-relaxed text-fg-muted"
          >
            Credyx resolves a business against 112 national registries, pulls its
            filed financials, and returns a deterministic risk assessment — every
            number sourced, every step auditable.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: outExpo, delay: 0.2 }}
            className="mt-9 flex flex-wrap items-center gap-3"
          >
            <Button asChild size="lg" variant="primary" rightIcon={<ArrowRight className="h-4 w-4" />}>
              <Link href="/register">Start free trial</Link>
            </Button>
            <Button asChild size="lg" variant="ghost" leftIcon={<PlayCircle className="h-4 w-4" />}>
              <Link href="#how-it-works">Watch 2-min demo</Link>
            </Button>
          </motion.div>

          {/* Trust preview */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, ease: outExpo, delay: 0.32 }}
            className="mt-10 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs uppercase tracking-[0.2em] text-fg-subtle"
          >
            <span className="font-mono">Trusted by</span>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              {PREVIEW_LOGOS.map((l) => (
                <span
                  key={l}
                  className="rounded-md border border-border-default/70 bg-bg-elevated/40 px-2.5 py-1 font-mono text-[0.65rem] tracking-[0.16em] text-fg-muted backdrop-blur"
                >
                  {l}
                </span>
              ))}
            </div>
          </motion.div>
        </motion.div>

        {/* Right — glass mock card */}
        <motion.div
          initial={{ opacity: 0, y: 36 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...spring, delay: 0.18 }}
          className="relative"
        >
          <HeroMock />
        </motion.div>
      </div>
    </section>
  );
}

function HeroMock() {
  return (
    <div className="relative">
      {/* halo glow */}
      <div
        aria-hidden
        className="absolute -inset-12 -z-10 rounded-[3rem] bg-gradient-to-br from-brand-primary/25 via-accent/15 to-brand-secondary/20 opacity-70 blur-3xl"
      />

      <div className="plate relative rounded-2xl border border-border-default/80 bg-bg-elevated/60 p-6 shadow-depth-3 backdrop-blur-xl">
        {/* edge highlight */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-fg-default/15 to-transparent"
        />

        {/* Certificate serial strip */}
        <div className="mb-4 flex items-center justify-between border-b border-border-default/60 pb-3">
          <span className="serial">Certificate of assessment</span>
          <span className="font-mono text-[0.6rem] tracking-[0.18em] text-brand-secondary">
            N° CX-2026-000082
          </span>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-fg-subtle">
              Risk Engine · Live
            </div>
            <div className="mt-1 font-display text-base font-semibold tracking-tight text-fg-default">
              Acme Industries GmbH
            </div>
          </div>
          <span className="stamp stamp-good">Approve</span>
        </div>

        {/* Gauge + score */}
        <div className="mt-6 flex items-center gap-6">
          <RiskGauge value={82} />
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[0.62rem] uppercase tracking-[0.18em] text-fg-subtle">
              Score
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default tabular-nums">
                82
              </span>
              <span className="text-xs text-fg-muted">/ 100</span>
            </div>
            <div className="mt-1 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-success">
              Low risk · High confidence
            </div>
          </div>
        </div>

        {/* Ratios */}
        <div className="mt-6 space-y-3 border-t border-border-default/60 pt-5">
          <RatioRow
            icon={<TrendingUp className="h-3.5 w-3.5" />}
            label="Current ratio"
            value="1.82"
            data={SPARK_A}
            tone="success"
          />
          <RatioRow
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Debt / equity"
            value="0.41"
            data={SPARK_B}
            tone="accent"
          />
          <RatioRow
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
            label="Altman-Z"
            value="3.96"
            data={SPARK_C}
            tone="brand"
          />
        </div>

        <div className="mt-6 flex items-center justify-between border-t border-border-default/60 pt-4 font-mono text-[0.62rem] uppercase tracking-[0.18em] text-fg-subtle">
          <span>Recommended limit</span>
          <span className="text-fg-default">€ 2,400,000</span>
        </div>
      </div>
    </div>
  );
}

function RiskGauge({ value }: { value: number }) {
  const R = 36;
  const C = 2 * Math.PI * R;
  const offset = C - (value / 100) * C;

  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg viewBox="0 0 96 96" className="h-full w-full -rotate-90">
        <circle
          cx="48"
          cy="48"
          r={R}
          fill="none"
          stroke="hsl(var(--color-border-default))"
          strokeWidth="6"
          opacity="0.5"
        />
        <motion.circle
          cx="48"
          cy="48"
          r={R}
          fill="none"
          stroke="url(#gaugeGrad)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={C}
          initial={{ strokeDashoffset: C }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.6, ease: outExpo, delay: 0.4 }}
        />
        <defs>
          <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="hsl(var(--color-brand-primary))" />
            <stop offset="100%" stopColor="hsl(var(--color-success))" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="font-mono text-[0.6rem] uppercase tracking-[0.16em] text-fg-subtle">
          Risk
        </span>
      </div>
    </div>
  );
}

function RatioRow({
  icon,
  label,
  value,
  data,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  data: number[];
  tone: "success" | "accent" | "brand";
}) {
  const colorVar =
    tone === "success"
      ? "hsl(var(--color-success))"
      : tone === "accent"
      ? "hsl(var(--color-accent))"
      : "hsl(var(--color-brand-primary))";

  return (
    <div className="flex items-center gap-3">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-border-default/70 bg-bg-overlay/50 text-fg-muted">
        {icon}
      </span>
      <div className="flex-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-fg-muted">{label}</span>
          <span className="font-mono font-medium text-fg-default tabular-nums">{value}</span>
        </div>
        <Sparkline data={data} width={200} height={20} color={colorVar} fill className="mt-1 w-full" />
      </div>
    </div>
  );
}
