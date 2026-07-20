import type { Metadata } from "next";
import Link from "next/link";
import { Lock, Database, FileCheck2, UserCog, Gauge, ShieldAlert } from "lucide-react";

const TITLE = "Security — Credyx";
const DESCRIPTION =
  "How Credyx protects customer data: TLS everywhere, audit-ready assessments, role-based access, and data straight from official registries.";

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

const PRACTICES = [
  {
    icon: Lock,
    title: "Encryption in transit",
    body: "All traffic — browser, API, and registry fetches — runs over TLS. Public endpoints sit behind Cloudflare, which terminates TLS and absorbs volumetric attacks before they reach origin.",
  },
  {
    icon: Database,
    title: "Data provenance",
    body: "Company data comes directly from official government registries and free public aggregators. Every figure traces to a source document URL; nothing is fabricated, interpolated, or bought from data brokers.",
  },
  {
    icon: FileCheck2,
    title: "Audit-ready by design",
    body: "Risk assessments are persisted permanently with the exact ratios, signals, and model version that produced them, so any past credit decision can be reconstructed and defended.",
  },
  {
    icon: UserCog,
    title: "Role-based access",
    body: "Administrative functions are gated behind a separate admin role. Regular accounts can never reach user management, plan configuration, or audit logs.",
  },
  {
    icon: Gauge,
    title: "Rate limiting and quotas",
    body: "Per-account rate limits and plan quotas are enforced server-side on every endpoint — including internal traffic. There is no bypass tier.",
  },
  {
    icon: ShieldAlert,
    title: "Sanctions-aware pipeline",
    body: "OpenSanctions screening runs alongside registry lookups, so sanctioned or PEP-linked counterparties are flagged rather than silently scored.",
  },
];

export default function SecurityPage() {
  return (
    <>
      <section className="border-b border-border-default pb-20 pt-24">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <p className="serial">Legal</p>
            <h1 className="mt-3 font-display text-display-lg tracking-tight">
              Security at Credyx
            </h1>
            <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-fg-subtle">
              Last updated: July 2026
            </p>
            <p className="mt-6 text-lg leading-relaxed text-fg-muted">
              Credyx exists to make credit decisions defensible, which means the
              platform itself has to be defensible. This page describes the concrete
              measures we take today — no more, no less.
            </p>
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-20">
        <div className="container">
          <div className="mx-auto grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-2">
            {PRACTICES.map((p) => (
              <div
                key={p.title}
                className="rounded-xl border border-border-default bg-bg-elevated p-6 shadow-elev-1"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-border-default bg-bg-base">
                  <p.icon className="h-5 w-5 text-accent" aria-hidden />
                </div>
                <h3 className="mt-5 text-base font-semibold tracking-tight">
                  {p.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-fg-muted">{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-20">
        <div className="container">
          <div className="mx-auto max-w-3xl space-y-12 text-[0.95rem] leading-relaxed text-fg-muted">
            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                Infrastructure
              </h2>
              <p>
                The platform runs on managed cloud infrastructure: PostgreSQL for
                persistent data with encryption at rest, Redis for rate limiting and
                queues, and isolated worker processes for registry scraping so
                third-party fetches never run in the request path with user
                credentials. Database access from outside the private network is
                closed. Secrets are injected via environment configuration, never
                committed to source control.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                Authentication and payments
              </h2>
              <p>
                Passwords are stored only as salted hashes. Sessions use short-lived
                bearer tokens that are revocable server-side; changing your password
                invalidates all existing tokens. Card data never touches our servers —
                payment processing is delegated entirely to our payment provider.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                What we deliberately don&rsquo;t do
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  No mock or fallback data. If a registry cannot answer, the API says
                  so with an explicit error — a fabricated number in a credit decision
                  is a security problem, not a UX problem.
                </li>
                <li>
                  No arithmetic in the language model. Financial ratios are computed
                  deterministically in code before any model sees them.
                </li>
                <li>
                  No paid data brokers. Sources are official registries and free
                  public aggregators, so there is no shadow copy of your
                  counterparties&rsquo; data circulating through resellers on our
                  account.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                Certifications
              </h2>
              <p>
                Credyx does not currently hold SOC 2 or ISO/IEC 27001 certification,
                and we won&rsquo;t imply otherwise. Our practices are informed by
                those frameworks, and we will update this page as our compliance
                program matures. Enterprise customers can request our current security
                questionnaire responses via{" "}
                <a
                  href="mailto:security@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  security@credyx.ai
                </a>
                .
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                Responsible disclosure
              </h2>
              <p>
                If you believe you have found a vulnerability, email{" "}
                <a
                  href="mailto:security@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  security@credyx.ai
                </a>{" "}
                with reproduction steps. We commit to acknowledging reports within two
                business days and will not pursue action against good-faith research
                that avoids privacy violations and service disruption.
              </p>
              <p>
                For how we handle personal data, see the{" "}
                <Link
                  href="/privacy"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  privacy policy
                </Link>{" "}
                and{" "}
                <Link
                  href="/dpa"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  data processing agreement
                </Link>
                .
              </p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
