import type { Metadata } from "next";
import Link from "next/link";
import { Linkedin } from "lucide-react";
import { CTABanner } from "@/components/marketing/CTABanner";

const TITLE = "Team — Credyx";
const DESCRIPTION =
  "The people behind Credyx — a credit-risk operator and an engineer, building credit intelligence on the world's official registries.";

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

interface Member {
  name: string;
  role: string;
  initials: string;
  location: string;
  linkedin: string;
  bio: string;
  highlights: string[];
  gradient: string;
}

const TEAM: Member[] = [
  {
    name: "Albanda Musalzade",
    role: "Co-Founder & Tech Lead",
    initials: "AM",
    location: "Baku · Remote",
    linkedin: "https://www.linkedin.com/in/albanda/",
    bio: "Albanda builds the engine room of Credyx — the country-adapter network that pulls live data from 60+ official government registries, the deterministic risk engine, and the platform that ties it all together. He owns architecture, data engineering and the product surface end to end.",
    highlights: [
      "60+ live registry adapters",
      "Deterministic ratio engine",
      "Full-stack platform & infra",
    ],
    gradient:
      "linear-gradient(135deg, hsl(var(--color-brand-primary)) 0%, hsl(var(--color-accent)) 55%, hsl(var(--color-brand-secondary)) 100%)",
  },
  {
    name: "Tural Jabbarov",
    role: "Co-Founder",
    initials: "TJ",
    location: "Poznań, Poland · Hybrid",
    linkedin: "https://www.linkedin.com/in/tural-jabbarov-phd-c-6b89a211b/",
    bio: "Tural brings a decade of front-line credit-risk leadership across global industrial and consumer businesses — as a Credit Risk Manager for EMEA, a Regional AR & Credit Controller, and a Credit Risk Assessment Analyst. A PhD candidate in the field, he shapes Credyx's scoring methodology, industry ratio benchmarks and the analyst-grade judgment behind every assessment.",
    highlights: [
      "Credit Risk Manager, EMEA",
      "AR & Credit Controller",
      "Credit Risk Assessment Analyst",
    ],
    gradient:
      "linear-gradient(135deg, hsl(var(--color-brand-secondary)) 0%, hsl(var(--color-brand-primary)) 60%, hsl(var(--color-accent)) 100%)",
  },
];

export default function TeamPage() {
  return (
    <>
      <section className="relative isolate overflow-hidden border-b border-border-default pb-20 pt-24">
        {/* Engraved guilloché wash */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-1/2 [mask-image:linear-gradient(to_bottom,black,transparent)]"
        >
          <div className="texture-guilloche absolute inset-0 text-brand-primary/[0.07]" />
        </div>

        <div className="container">
          <div className="mx-auto max-w-3xl">
            <p className="serial text-accent">The founders</p>
            <h1 className="mt-3 font-display text-display-xl tracking-tight">
              Two founders: the risk desk and the engine room.
            </h1>
            <p className="mt-6 text-lg leading-relaxed text-fg-muted">
              Credyx is built by people who have sat on both sides of a credit
              decision — the operator who has to sign off on the limit, and the
              engineer who can reach the primary source in seconds. That pairing is
              the whole product.
            </p>
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-20">
        <div className="container">
          <div className="mx-auto grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-2">
            {TEAM.map((m) => (
              <article
                key={m.name}
                className="plate group relative flex flex-col overflow-hidden rounded-2xl border border-border-default bg-bg-elevated p-7 shadow-elev-1 transition-colors hover:border-border-strong"
              >
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent"
                />

                <div className="flex items-center gap-4">
                  {/* Monogram seal */}
                  <span className="relative grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-2xl border border-border-strong/70 shadow-depth-1">
                    <span
                      aria-hidden
                      className="absolute inset-0"
                      style={{ background: m.gradient }}
                    />
                    <span className="absolute inset-0 bg-bg-inset/45" />
                    <span className="relative font-display text-xl font-semibold tracking-tight text-fg-default">
                      {m.initials}
                    </span>
                  </span>

                  <div className="min-w-0">
                    <h2 className="font-display text-xl font-semibold tracking-tight">
                      {m.name}
                    </h2>
                    <p className="mt-0.5 text-sm font-medium text-brand-primary">
                      {m.role}
                    </p>
                    <p className="mt-1 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-fg-subtle">
                      {m.location}
                    </p>
                  </div>
                </div>

                <p className="mt-5 text-sm leading-relaxed text-fg-muted">{m.bio}</p>

                <div className="mt-5 space-y-2 border-t border-border-default/60 pt-5">
                  {m.highlights.map((h) => (
                    <div key={h} className="flex items-center gap-2.5 text-sm">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-secondary shadow-[0_0_8px_hsl(var(--color-brand-secondary)/0.6)]" />
                      <span className="text-fg-default">{h}</span>
                    </div>
                  ))}
                </div>

                <div className="mt-6 flex-1" />

                <a
                  href={m.linkedin}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex w-fit items-center gap-2 rounded-lg border border-border-default px-3.5 py-2 text-sm font-medium text-fg-muted transition-colors hover:border-brand-primary/50 hover:bg-bg-overlay hover:text-fg-default"
                >
                  <Linkedin className="h-4 w-4" aria-hidden />
                  Connect on LinkedIn
                </a>
              </article>
            ))}
          </div>

          <div className="mx-auto mt-12 max-w-5xl">
            <div className="rule-ornament font-mono text-[0.62rem] uppercase tracking-[0.2em] text-fg-subtle">
              <span>Building the team</span>
            </div>
            <p className="mx-auto mt-6 max-w-2xl text-center text-sm leading-relaxed text-fg-muted">
              We&apos;re a small, senior team and we hire like it. If credit risk,
              data engineering or government-registry plumbing is your idea of a good
              time, we want to hear from you.
            </p>
            <div className="mt-6 flex justify-center">
              <Link
                href="/careers"
                className="inline-flex items-center gap-2 rounded-lg bg-brand-primary px-4 py-2.5 text-sm font-semibold text-brand-primary-fg transition hover:bg-brand-primary/90"
              >
                See open roles
              </Link>
            </div>
          </div>
        </div>
      </section>

      <CTABanner />
    </>
  );
}
