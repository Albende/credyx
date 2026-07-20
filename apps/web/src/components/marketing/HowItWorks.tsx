"use client";

import * as React from "react";
import { motion, useInView, useScroll, useTransform } from "framer-motion";
import { Search, Download, Sparkles, type LucideIcon } from "lucide-react";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { Reveal } from "@/components/ui/reveal";
import { outExpo } from "@/lib/motion";

type Step = {
  n: number;
  icon: LucideIcon;
  title: string;
  description: string;
  bullets: string[];
};

const STEPS: Step[] = [
  {
    n: 1,
    icon: Search,
    title: "Search",
    description: "Type a company name or VAT / registry identifier.",
    bullets: [
      "Fuzzy name match via pg_trgm",
      "Direct lookup by VAT / LEI / CIN",
      "Country auto-detection",
    ],
  },
  {
    n: 2,
    icon: Download,
    title: "Pull",
    description: "We fetch registry data and filed financials directly from official sources.",
    bullets: [
      "XBRL filings from SEC, EDINET, DART, ESEF",
      "Sanctions + PEP screening via OpenSanctions",
      "Cached 7d / 30d for repeat lookups",
    ],
  },
  {
    n: 3,
    icon: Sparkles,
    title: "Score",
    description: "Deterministic ratios plus AI synthesis return a credit decision.",
    bullets: [
      "Score 0-100 with confidence band",
      "APPROVE / REVIEW / REJECT recommendation",
      "Recommended credit limit in EUR",
    ],
  },
];

export function HowItWorks() {
  const sectionRef = React.useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start 80%", "end 30%"],
  });

  // Gradient flow along connector — scaleX 0 to 1 across the section
  const flowX = useTransform(scrollYProgress, [0, 1], [0, 1]);

  return (
    <section
      id="how-it-works"
      ref={sectionRef}
      className="relative overflow-hidden border-b border-border-default py-24 md:py-32"
    >
      <div
        aria-hidden
        className="absolute inset-0 bg-grid bg-[length:40px_40px] opacity-[0.04]"
      />
      <div className="container relative">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-accent">
              How it works
            </p>
            <h2 className="mt-4 font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default text-balance sm:text-6xl">
              Three steps from name to decision.
            </h2>
            <p className="mt-5 text-lg text-fg-muted">
              The boring path is the right path. Search, pull, score &mdash; no surprises
              in between.
            </p>
          </div>
        </Reveal>

        <div className="relative mt-20">
          {/* Horizontal connector with scroll-linked gradient flow */}
          <div
            aria-hidden
            className="pointer-events-none absolute left-[8%] right-[8%] top-10 hidden h-px md:block"
          >
            <div className="absolute inset-0 bg-border-default" />
            <motion.div
              className="absolute inset-0 origin-left bg-gradient-to-r from-brand-primary via-accent to-brand-secondary"
              style={{ scaleX: flowX }}
            />
          </div>

          <div className="grid grid-cols-1 gap-10 md:grid-cols-3 md:gap-6">
            {STEPS.map((step, i) => (
              <StepCard key={step.n} step={step} index={i} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function StepCard({ step, index }: { step: Step; index: number }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  const Icon = step.icon;

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 28 }}
      animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 28 }}
      transition={{ duration: 0.65, delay: index * 0.15, ease: outExpo }}
      className="relative flex flex-col items-center text-center md:items-start md:text-left"
    >
      {/* Numbered badge — sits on connector */}
      <div className="relative z-10 flex h-20 w-20 items-center justify-center rounded-full border border-border-strong bg-bg-elevated shadow-depth-2">
        <div className="absolute inset-1.5 rounded-full bg-gradient-to-br from-brand-primary/15 via-transparent to-accent/15" />
        <span className="relative font-display text-3xl font-semibold tabular-nums text-fg-default">
          <AnimatedCounter value={step.n} duration={1.2} />
        </span>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <span className="grid h-9 w-9 place-items-center rounded-lg border border-border-default bg-bg-elevated text-brand-primary">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <h3 className="font-display text-2xl font-semibold tracking-tight text-fg-default">
          {step.title}
        </h3>
      </div>

      <p className="mt-3 max-w-xs text-base text-fg-muted">{step.description}</p>

      <ul className="mt-6 w-full max-w-xs space-y-2.5 border-t border-border-default/70 pt-5">
        {step.bullets.map((b) => (
          <li
            key={b}
            className="flex items-start gap-2.5 text-sm text-fg-muted"
          >
            <span
              className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full bg-accent"
              aria-hidden
            />
            <span>{b}</span>
          </li>
        ))}
      </ul>
    </motion.div>
  );
}
