import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Check, Minus, Sparkles } from "lucide-react";
import { PricingTeaser } from "@/components/marketing/PricingTeaser";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Reveal } from "@/components/ui/reveal";
import { BentoCard } from "@/components/ui/bento-card";
import { AuroraText } from "@/components/ui/aurora-text";
import { MeshGradient } from "@/components/ui/mesh-gradient";
import { Grain } from "@/components/ui/grain";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { cn } from "@/lib/cn";

export const dynamic = "force-dynamic";

const TITLE = "Pricing — Credyx";
const DESCRIPTION =
  "Simple per-volume pricing. Start free, scale up to Enterprise. The same live registry data on every plan.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    images: ["/og/og-home.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: ["/og/og-home.png"],
  },
};

type Cell = string | boolean;

type CompareRow = {
  feature: string;
  description?: string;
  free: Cell;
  starter: Cell;
  pro: Cell;
  enterprise: Cell;
};

const COMPARE_ROWS: CompareRow[] = [
  {
    feature: "Risk reports / month",
    description: "AI risk scores with deterministic ratios + LLM commentary",
    free: "10",
    starter: "250",
    pro: "2,500",
    enterprise: "Unlimited",
  },
  {
    feature: "Live registry searches / day",
    description: "Real-time lookups across 112 country adapters",
    free: "25",
    starter: "500",
    pro: "5,000",
    enterprise: "Unlimited",
  },
  {
    feature: "Country coverage",
    description: "Official government registries + GLEIF + OpenCorporates",
    free: "112 countries",
    starter: "112 countries",
    pro: "112 countries",
    enterprise: "112 countries",
  },
  {
    feature: "Sanctions & PEP screening",
    description: "OpenSanctions matches with auto-reject on high confidence",
    free: true,
    starter: true,
    pro: true,
    enterprise: true,
  },
  {
    feature: "Filed financials & XBRL parsing",
    description: "Structured balance sheet & P&L from filings",
    free: false,
    starter: true,
    pro: true,
    enterprise: true,
  },
  {
    feature: "PDF report export",
    description: "Branded credit memos with deterministic ratios",
    free: false,
    starter: true,
    pro: true,
    enterprise: true,
  },
  {
    feature: "API access",
    description: "Personal keys with rotation and per-key rate limits",
    free: false,
    starter: false,
    pro: true,
    enterprise: true,
  },
  {
    feature: "Bulk batch processing",
    description: "Upload CSV portfolios, get scored output async",
    free: false,
    starter: false,
    pro: true,
    enterprise: true,
  },
  {
    feature: "Support",
    description: "Response time and channels",
    free: "Community",
    starter: "Email · 24h",
    pro: "Priority · 4h SLA",
    enterprise: "Dedicated CSM",
  },
  {
    feature: "Deployment & security",
    description: "Where the platform runs and the contracts behind it",
    free: "Multi-tenant",
    starter: "Multi-tenant",
    pro: "Multi-tenant + SSO",
    enterprise: "On-prem · DPA · SOC2",
  },
];

const BILLING_FAQS: { q: string; a: React.ReactNode }[] = [
  {
    q: "Can I switch plans or cancel any time?",
    a: (
      <>
        Yes. Upgrades take effect immediately and we pro-rate the difference for
        the rest of the billing cycle. Downgrades take effect at the next renewal
        so you keep the volume you&rsquo;ve already paid for. Cancel from your
        billing settings &mdash; no email gymnastics, no retention calls.
      </>
    ),
  },
  {
    q: "What happens when I hit my monthly limit?",
    a: (
      <>
        We notify you at 80% and 100% of your report quota. On Free and Starter
        the engine pauses risk analysis until the next cycle &mdash; registry
        lookups keep working. On Pro and Enterprise you can opt in to metered
        overage at the per-report rate of the next tier up, billed monthly in
        arrears.
      </>
    ),
  },
  {
    q: "Do you offer annual billing or volume discounts?",
    a: (
      <>
        Annual billing is 20% off the monthly rate on Starter and Pro. For
        Enterprise we price per committed annual report volume with custom
        terms, including dedicated regions, SSO, audit logs, and a signed DPA.
        Talk to sales for a quote.
      </>
    ),
  },
  {
    q: "Which payment methods and currencies do you accept?",
    a: (
      <>
        All major cards (Visa, Mastercard, Amex), SEPA direct debit and ACH on
        annual plans. We bill in USD, EUR or GBP &mdash; pick the currency you
        prefer at checkout. Enterprise invoices can be paid by wire on NET-30
        terms.
      </>
    ),
  },
];

function PlanHeader({
  name,
  price,
  cadence,
  highlight = false,
}: {
  name: string;
  price: string;
  cadence?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 px-5 py-5",
        highlight && "bg-brand-primary/[0.06]",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-display text-base font-semibold tracking-tight text-fg-default">
          {name}
        </span>
        {highlight && (
          <Badge variant="brand" className="text-[10px] uppercase">
            Popular
          </Badge>
        )}
      </div>
      <div className="flex items-baseline gap-1">
        <span className="font-display text-2xl font-semibold tracking-tight text-fg-default">
          {price}
        </span>
        {cadence && (
          <span className="text-xs text-fg-muted">/ {cadence}</span>
        )}
      </div>
    </div>
  );
}

function CellRender({ value, highlight }: { value: Cell; highlight?: boolean }) {
  if (typeof value === "boolean") {
    return value ? (
      <Check
        aria-label="Included"
        className={cn(
          "mx-auto h-4 w-4",
          highlight ? "text-brand-primary" : "text-success",
        )}
      />
    ) : (
      <Minus aria-label="Not included" className="mx-auto h-4 w-4 text-fg-subtle" />
    );
  }
  return (
    <span
      className={cn(
        "text-sm",
        highlight ? "font-medium text-fg-default" : "text-fg-default",
      )}
    >
      {value}
    </span>
  );
}

export default function PricingPage() {
  return (
    <>
      <Grain />

      {/* 1. Hero band */}
      <section className="relative overflow-hidden border-b border-border-default pb-16 pt-28 md:pt-32">
        <MeshGradient intensity="subtle" />
        <div className="container relative">
          <Reveal className="mx-auto max-w-3xl text-center" stagger>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
              Pricing
            </p>
            <h1 className="mt-4 font-display text-display-xl tracking-tight">
              Pay for volume,{" "}
              <AuroraText>not for access.</AuroraText>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-fg-muted">
              Every plan ships with the full set of 112 country adapters,
              deterministic ratios and sanctions screening. Upgrade as your
              search and report volume grows &mdash; never to unlock the data.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <Button
                asChild
                size="lg"
                variant="primary"
                rightIcon={<ArrowRight className="h-4 w-4" />}
              >
                <Link href="/register">Start free</Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="#compare">Compare plans</Link>
              </Button>
            </div>
          </Reveal>
        </div>
      </section>

      {/* 2. Pricing teaser (will be redesigned in landing brief) */}
      <PricingTeaser />

      {/* 3. Compare plans table */}
      <section
        id="compare"
        className="border-b border-border-default py-24 md:py-32"
      >
        <div className="container">
          <Reveal className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
              Compare plans
            </p>
            <h2 className="mt-3 font-display text-display-lg tracking-tight">
              Every feature, side by side.
            </h2>
            <p className="mt-4 text-lg text-fg-muted">
              The same registry data on every tier. What changes is volume,
              automation and the way you ship it into your stack.
            </p>
          </Reveal>

          <Reveal className="mx-auto mt-14 max-w-6xl">
            <div className="overflow-hidden rounded-2xl border border-border-default bg-bg-elevated shadow-depth-1">
              {/* Desktop / tablet table */}
              <div className="hidden md:block">
                <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr_1fr] border-b border-border-default">
                  <div className="px-5 py-5">
                    <span className="font-mono text-[0.68rem] font-medium uppercase tracking-[0.14em] text-fg-subtle">
                      Features
                    </span>
                  </div>
                  <PlanHeader name="Free" price="$0" cadence="forever" />
                  <PlanHeader name="Starter" price="$19" cadence="month" />
                  <PlanHeader name="Pro" price="$79" cadence="month" highlight />
                  <PlanHeader name="Enterprise" price="Custom" />
                </div>

                <ul className="divide-y divide-border-default">
                  {COMPARE_ROWS.map((row) => (
                    <li
                      key={row.feature}
                      className="grid grid-cols-[1.4fr_1fr_1fr_1fr_1fr] items-center"
                    >
                      <div className="px-5 py-5">
                        <div className="text-sm font-medium text-fg-default">
                          {row.feature}
                        </div>
                        {row.description && (
                          <div className="mt-1 text-xs text-fg-muted">
                            {row.description}
                          </div>
                        )}
                      </div>
                      <div className="px-5 py-5 text-center">
                        <CellRender value={row.free} />
                      </div>
                      <div className="px-5 py-5 text-center">
                        <CellRender value={row.starter} />
                      </div>
                      <div className="bg-brand-primary/[0.04] px-5 py-5 text-center">
                        <CellRender value={row.pro} highlight />
                      </div>
                      <div className="px-5 py-5 text-center">
                        <CellRender value={row.enterprise} />
                      </div>
                    </li>
                  ))}
                </ul>

                <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr_1fr] border-t border-border-default">
                  <div className="px-5 py-5" />
                  <div className="px-5 py-5">
                    <Button asChild variant="secondary" className="w-full">
                      <Link href="/register">Start free</Link>
                    </Button>
                  </div>
                  <div className="px-5 py-5">
                    <Button asChild variant="secondary" className="w-full">
                      <Link href="/register?plan=starter">Choose Starter</Link>
                    </Button>
                  </div>
                  <div className="bg-brand-primary/[0.04] px-5 py-5">
                    <Button asChild variant="primary" className="w-full">
                      <Link href="/register?plan=pro">Choose Pro</Link>
                    </Button>
                  </div>
                  <div className="px-5 py-5">
                    <Button asChild variant="outline" className="w-full">
                      <Link href="/contact">Talk to sales</Link>
                    </Button>
                  </div>
                </div>
              </div>

              {/* Mobile stacked plans */}
              <div className="md:hidden">
                {(
                  [
                    {
                      key: "free" as const,
                      name: "Free",
                      price: "$0",
                      cadence: "forever",
                      cta: "Start free",
                      href: "/register",
                      variant: "secondary" as const,
                    },
                    {
                      key: "starter" as const,
                      name: "Starter",
                      price: "$19",
                      cadence: "month",
                      cta: "Choose Starter",
                      href: "/register?plan=starter",
                      variant: "secondary" as const,
                    },
                    {
                      key: "pro" as const,
                      name: "Pro",
                      price: "$79",
                      cadence: "month",
                      cta: "Choose Pro",
                      href: "/register?plan=pro",
                      variant: "primary" as const,
                      highlight: true,
                    },
                    {
                      key: "enterprise" as const,
                      name: "Enterprise",
                      price: "Custom",
                      cta: "Talk to sales",
                      href: "/contact",
                      variant: "outline" as const,
                    },
                  ]
                ).map((plan) => (
                  <div
                    key={plan.key}
                    className={cn(
                      "border-b border-border-default px-5 py-6 last:border-b-0",
                      plan.highlight && "bg-brand-primary/[0.05]",
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-display text-base font-semibold tracking-tight text-fg-default">
                          {plan.name}
                        </span>
                        {plan.highlight && (
                          <Badge variant="brand" className="text-[10px] uppercase">
                            Popular
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-baseline gap-1">
                        <span className="font-display text-xl font-semibold tracking-tight text-fg-default">
                          {plan.price}
                        </span>
                        {plan.cadence && (
                          <span className="text-xs text-fg-muted">
                            / {plan.cadence}
                          </span>
                        )}
                      </div>
                    </div>
                    <ul className="mt-4 space-y-2.5 border-t border-border-default pt-4">
                      {COMPARE_ROWS.map((row) => {
                        const value = row[plan.key];
                        return (
                          <li
                            key={row.feature}
                            className="flex items-start justify-between gap-3 text-sm"
                          >
                            <span className="text-fg-muted">{row.feature}</span>
                            <span className="text-right text-fg-default">
                              {typeof value === "boolean" ? (
                                value ? (
                                  <Check className="ml-auto h-4 w-4 text-success" />
                                ) : (
                                  <Minus className="ml-auto h-4 w-4 text-fg-subtle" />
                                )
                              ) : (
                                value
                              )}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                    <Button
                      asChild
                      variant={plan.variant}
                      className="mt-5 w-full"
                    >
                      <Link href={plan.href}>{plan.cta}</Link>
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* 4. Enterprise CTA card */}
      <section className="border-b border-border-default py-24 md:py-32">
        <div className="container">
          <Reveal className="mx-auto max-w-5xl">
            <BentoCard className="relative overflow-hidden border-border-strong p-0">
              <div className="absolute inset-0">
                <MeshGradient intensity="vivid" />
              </div>
              <div className="relative grid gap-10 p-10 md:grid-cols-[1.4fr_1fr] md:p-14">
                <div>
                  <div className="inline-flex items-center gap-2 rounded-full border border-border-strong bg-bg-overlay/70 px-3 py-1 text-xs font-medium text-fg-default backdrop-blur">
                    <Sparkles className="h-3.5 w-3.5 text-brand-primary" />
                    Enterprise
                  </div>
                  <h2 className="mt-5 font-display text-display-lg tracking-tight">
                    Built for credit teams running{" "}
                    <AuroraText>portfolios at scale.</AuroraText>
                  </h2>
                  <p className="mt-5 max-w-xl text-lg text-fg-muted">
                    Unlimited volume, dedicated regions, SSO, audit logs and a
                    signed DPA. On-prem and air-gapped deployments available for
                    regulated environments. Custom country adapters built to
                    your priorities.
                  </p>
                  <ul className="mt-6 grid gap-2.5 sm:grid-cols-2">
                    {[
                      "Unlimited reports & API calls",
                      "On-prem / VPC deployment",
                      "SSO (SAML, OIDC) + audit logs",
                      "Signed DPA · SOC2 controls",
                      "Dedicated CSM & 1h SLA",
                      "Custom country adapters",
                    ].map((item) => (
                      <li
                        key={item}
                        className="flex items-start gap-2 text-sm text-fg-default"
                      >
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-primary" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-8 flex flex-wrap items-center gap-3">
                    <Button
                      asChild
                      size="lg"
                      variant="primary"
                      rightIcon={<ArrowRight className="h-4 w-4" />}
                    >
                      <Link href="/contact">Talk to sales</Link>
                    </Button>
                    <Button asChild size="lg" variant="outline">
                      <Link href="/docs">Read the docs</Link>
                    </Button>
                  </div>
                </div>

                <div className="relative flex flex-col justify-center">
                  <div className="rounded-xl border border-border-strong bg-bg-elevated/70 p-6 backdrop-blur">
                    <div className="font-mono text-[0.68rem] font-medium uppercase tracking-[0.14em] text-fg-subtle">
                      Typical engagement
                    </div>
                    <dl className="mt-4 space-y-4">
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-sm text-fg-muted">Onboarding</dt>
                        <dd className="font-display text-base font-semibold text-fg-default">
                          &lt; 2 weeks
                        </dd>
                      </div>
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-sm text-fg-muted">Uptime SLA</dt>
                        <dd className="font-display text-base font-semibold text-fg-default">
                          99.95%
                        </dd>
                      </div>
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-sm text-fg-muted">Support SLA</dt>
                        <dd className="font-display text-base font-semibold text-fg-default">
                          1h response
                        </dd>
                      </div>
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-sm text-fg-muted">Deployment</dt>
                        <dd className="font-display text-base font-semibold text-fg-default">
                          Cloud · VPC · On-prem
                        </dd>
                      </div>
                    </dl>
                  </div>
                  <p className="mt-4 text-xs text-fg-subtle">
                    Pricing scales with committed annual report volume. Most
                    Enterprise deals close in under 30 days.
                  </p>
                </div>
              </div>
            </BentoCard>
          </Reveal>
        </div>
      </section>

      {/* 5. Billing FAQ */}
      <section className="border-b border-border-default py-24 md:py-32">
        <div className="container">
          <Reveal className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
              Billing FAQ
            </p>
            <h2 className="mt-3 font-display text-display-lg tracking-tight">
              The fine print, without the fine print.
            </h2>
            <p className="mt-4 text-lg text-fg-muted">
              Straight answers about plans, limits, invoices and renewals.
            </p>
          </Reveal>

          <Reveal className="mx-auto mt-12 max-w-3xl">
            <Accordion type="single" collapsible className="w-full">
              {BILLING_FAQS.map((f, i) => (
                <AccordionItem key={f.q} value={`billing-faq-${i}`}>
                  <AccordionTrigger className="text-left">{f.q}</AccordionTrigger>
                  <AccordionContent className="text-fg-muted">
                    {f.a}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </Reveal>
        </div>
      </section>

      {/* 6. Footer CTA banner */}
      <section className="relative overflow-hidden py-24 md:py-32">
        <MeshGradient intensity="normal" />
        <div className="container relative">
          <Reveal className="mx-auto max-w-3xl">
            <div className="relative overflow-hidden rounded-2xl border border-border-strong bg-bg-elevated/70 p-10 text-center shadow-elev-3 backdrop-blur md:p-14">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent"
              />
              <h2 className="font-display text-display-lg tracking-tight">
                Start free,{" "}
                <AuroraText>no card required.</AuroraText>
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-lg text-fg-muted">
                Spin up an account in under a minute and run your first live
                registry lookup today. Upgrade when your volume catches up.
              </p>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <Button
                  asChild
                  size="lg"
                  variant="primary"
                  rightIcon={<ArrowRight className="h-4 w-4" />}
                >
                  <Link href="/register">Create your account</Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link href="/contact">Talk to sales</Link>
                </Button>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
