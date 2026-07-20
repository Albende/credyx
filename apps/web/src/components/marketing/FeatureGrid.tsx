"use client";

import {
  Globe,
  FileText,
  Calculator,
  ShieldAlert,
  Database,
  Bot,
  type LucideIcon,
} from "lucide-react";
import { BentoCard } from "@/components/ui/bento-card";
import { Reveal } from "@/components/ui/reveal";
import { Sparkline } from "@/components/ui/sparkline";

type Feature = {
  icon: LucideIcon;
  title: string;
  description: string;
  span: string;
  size: "lg" | "sm";
};

const FEATURES: Feature[] = [
  {
    icon: Globe,
    title: "Live search across 112 countries",
    description:
      "Companies House, SEC EDGAR, INSEE Sirene, KvK and 100+ more in a single call. GLEIF is a universal fallback for everything else.",
    span: "md:col-span-2 md:row-span-2",
    size: "lg",
  },
  {
    icon: FileText,
    title: "Filed financial reports",
    description:
      "XBRL balance sheets, P&L and cash flow from SEC, EDINET, DART and ESEF — parsed into a normalised schema.",
    span: "md:col-span-2",
    size: "lg",
  },
  {
    icon: Calculator,
    title: "Deterministic ratios",
    description:
      "Current, quick, D/E, ROE, ROA and Altman-Z computed before the LLM sees a number.",
    span: "md:col-span-1",
    size: "sm",
  },
  {
    icon: ShieldAlert,
    title: "OpenSanctions screening",
    description:
      "5M+ entities, PEPs and watchlists. High-confidence hits force auto-REJECT.",
    span: "md:col-span-1",
    size: "sm",
  },
  {
    icon: Database,
    title: "Bulk ingestion",
    description:
      "BE KBO, UA YeDR, LV UR, IL CKAN dumps indexed nightly with fuzzy pg_trgm search.",
    span: "md:col-span-1",
    size: "sm",
  },
  {
    icon: Bot,
    title: "AI risk synthesis",
    description:
      "Gemini scores 0-100 with structured reasoning, an APPROVE / REVIEW / REJECT call, and a recommended EUR limit.",
    span: "md:col-span-1",
    size: "sm",
  },
];

const FEATURE_SPARK = [44, 48, 46, 52, 56, 60, 63, 68, 72, 78, 82, 86, 90];

export function FeatureGrid() {
  return (
    <section
      id="features"
      className="relative border-b border-border-default py-24 md:py-32"
    >
      <div className="container">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-accent">
              Built for credit teams
            </p>
            <h2 className="mt-4 font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default text-balance sm:text-6xl">
              Every layer of the stack is real.
            </h2>
            <p className="mt-5 text-lg text-fg-muted">
              No mock data, no commercial paywalls. Government registries, deterministic
              math and a model that knows when to stay quiet.
            </p>
          </div>
        </Reveal>

        <Reveal stagger>
          <div className="mt-16 grid grid-cols-1 gap-4 md:grid-cols-4 md:auto-rows-[minmax(180px,_auto)]">
            {FEATURES.map((feature) => (
              <BentoCard
                key={feature.title}
                span={feature.span}
                icon={<feature.icon className="h-[18px] w-[18px]" />}
                eyebrow={feature.size === "lg" ? "Capability" : undefined}
                title={feature.title}
              >
                <p className="text-sm leading-relaxed text-fg-muted">
                  {feature.description}
                </p>

                {feature.icon === Globe && (
                  <div className="relative mt-6 h-32 overflow-hidden rounded-lg border border-border-default/60 bg-bg-base/40">
                    <div
                      aria-hidden
                      className="absolute inset-0 bg-grid bg-[length:24px_24px] opacity-[0.06]"
                    />
                    <div className="absolute inset-0 grid grid-cols-7 gap-1 p-3">
                      {Array.from({ length: 42 }).map((_, i) => {
                        const active = [3, 5, 8, 11, 14, 17, 18, 22, 27, 31, 33, 36, 39].includes(i);
                        return (
                          <div
                            key={i}
                            className={
                              active
                                ? "h-2 w-2 rounded-sm bg-brand-primary animate-pulse"
                                : "h-2 w-2 rounded-sm bg-border-default/60"
                            }
                            style={active ? { animationDelay: `${i * 40}ms` } : undefined}
                          />
                        );
                      })}
                    </div>
                  </div>
                )}

                {feature.icon === FileText && (
                  <div className="mt-5 grid grid-cols-3 gap-2">
                    {["XBRL", "iXBRL", "JSON"].map((tag) => (
                      <span
                        key={tag}
                        className="rounded-md border border-border-default/70 bg-bg-overlay/40 px-2 py-1 text-center font-mono text-[0.62rem] uppercase tracking-[0.14em] text-fg-muted"
                      >
                        {tag}
                      </span>
                    ))}
                    <div className="col-span-3 mt-1">
                      <Sparkline
                        data={FEATURE_SPARK}
                        width={300}
                        height={28}
                        color="hsl(var(--color-brand-primary))"
                        fill
                        className="w-full"
                      />
                    </div>
                  </div>
                )}
              </BentoCard>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
