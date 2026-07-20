"use client";

import { Globe, Building2, Library, FileText } from "lucide-react";
import { Marquee } from "@/components/ui/marquee";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { Reveal } from "@/components/ui/reveal";

const REGISTRY_LOGOS = [
  "UK Companies House",
  "SEC EDGAR",
  "INSEE Sirene",
  "KvK Netherlands",
  "Brønnøysund",
  "PRH Finland",
  "ARES Czech Republic",
  "Inforegister Estonia",
  "GLEIF",
  "OpenCorporates",
  "OpenSanctions",
  "BORME",
  "Handelsregister",
  "KRS Poland",
];

const COUNTERS: { value: number; suffix?: string; label: string; icon: typeof Globe }[] = [
  { value: 112, label: "country adapters", icon: Globe },
  { value: 8_000_000, suffix: "+", label: "companies indexed", icon: Building2 },
  { value: 35, suffix: "+", label: "registries integrated", icon: Library },
  { value: 1_200_000, suffix: "+", label: "filings parsed", icon: FileText },
];

function compactFormat(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return Math.round(n).toString();
}

export function TrustStrip() {
  return (
    <section className="relative border-y border-border-default/80 bg-bg-elevated/30">
      <div className="container py-14">
        <Reveal>
          <p className="text-center font-mono text-[0.65rem] uppercase tracking-[0.24em] text-fg-subtle">
            Sourced directly from official government registries
          </p>
        </Reveal>

        <div className="mt-8">
          <Marquee speed={45} pauseOnHover>
            {REGISTRY_LOGOS.map((name) => (
              <span
                key={name}
                className="select-none whitespace-nowrap font-display text-base font-medium tracking-tight text-fg-muted/80 transition-colors hover:text-fg-default"
              >
                {name}
              </span>
            ))}
          </Marquee>
        </div>

        <Reveal stagger>
          <div className="mt-14 grid grid-cols-2 gap-x-6 gap-y-10 sm:grid-cols-4">
            {COUNTERS.map((c) => (
              <div key={c.label} className="flex flex-col items-center text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border-default bg-bg-base text-accent">
                  <c.icon className="h-4 w-4" aria-hidden />
                </div>
                <div className="mt-3 font-display text-4xl font-semibold tracking-[-0.02em] text-fg-default">
                  <AnimatedCounter value={c.value} suffix={c.suffix} format={compactFormat} duration={2.4} />
                </div>
                <div className="mt-1 text-sm text-fg-muted">{c.label}</div>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
