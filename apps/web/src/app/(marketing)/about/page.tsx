import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { CTABanner } from "@/components/marketing/CTABanner";

const TITLE = "About — Credyx";
const DESCRIPTION =
  "Credyx is a B2B credit intelligence platform built on top of the world's official government registries.";

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

const PRINCIPLES = [
  {
    title: "No mock data, ever",
    body: "If a registry can't return real numbers, we surface that as a clean 501 rather than inventing a figure. Credit decisions deserve real inputs.",
  },
  {
    title: "Deterministic before intelligent",
    body: "All financial ratios are computed in pure Python before the LLM sees them. The model interprets — it never does arithmetic.",
  },
  {
    title: "Audit-ready by default",
    body: "Every risk assessment is persisted forever. Every figure traces back to a registry document you can pull on demand.",
  },
  {
    title: "Free sources first",
    body: "We integrate against government and free aggregator data. Paid commercial sources are a Phase-2 choice, never a Phase-1 lock-in.",
  },
];

export default function AboutPage() {
  return (
    <>
      <section className="border-b border-border-default pb-20 pt-24">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
              About
            </p>
            <h1 className="mt-3 font-display text-display-xl tracking-tight">
              Credit decisions built on real data, not vibes.
            </h1>
            <p className="mt-6 text-lg leading-relaxed text-fg-muted">
              Credyx started as the answer to a frustration that anyone running a
              credit desk knows by heart: it&apos;s 2026 and finding out whether a foreign
              counterparty is real, solvent and clean of sanctions still takes days,
              several phone calls and at least one PDF you can&apos;t parse.
            </p>
            <p className="mt-5 text-lg leading-relaxed text-fg-muted">
              We connect directly to the official source &mdash; Companies House, SEC EDGAR,
              INSEE Sirene, KvK, Brønnøysund, PRH, ARES, Inforegister and 100+ more &mdash;
              compute the ratios your analyst would, and pass the result to a model that
              has been told, very firmly, not to invent numbers. What comes back is a
              score, a recommendation, a credit limit and a paper trail.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-3">
              <Button asChild variant="primary" size="lg">
                <Link href="/register">Start free</Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link href="/team">Meet the team</Link>
              </Button>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-24">
        <div className="container">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
              Principles
            </p>
            <h2 className="mt-3 font-display text-display-lg tracking-tight">
              The non-negotiables.
            </h2>
          </div>
          <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-2">
            {PRINCIPLES.map((p) => (
              <div
                key={p.title}
                className="rounded-xl border border-border-default bg-bg-elevated p-6 shadow-elev-1"
              >
                <h3 className="text-base font-semibold tracking-tight">{p.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-fg-muted">{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CTABanner />
    </>
  );
}
