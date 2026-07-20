import Link from "next/link";
import { Check, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { Reveal } from "@/components/ui/reveal";
import { cn } from "@/lib/cn";

type Plan = {
  id: string;
  name: string;
  price_cents: number | null;
  currency?: string;
  interval?: "month" | "year";
  features: string[];
  popular?: boolean;
  cta_label?: string;
};

const FALLBACK_PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    price_cents: 0,
    currency: "USD",
    interval: "month",
    features: [
      "10 risk reports per month",
      "Live registry search",
      "Sanctions screening",
      "Community support",
    ],
    cta_label: "Start free",
  },
  {
    id: "starter",
    name: "Starter",
    price_cents: 1900,
    currency: "USD",
    interval: "month",
    features: [
      "250 risk reports per month",
      "Filed financials & XBRL parsing",
      "PDF report export",
      "Email support",
    ],
    cta_label: "Choose Starter",
  },
  {
    id: "pro",
    name: "Pro",
    price_cents: 7900,
    currency: "USD",
    interval: "month",
    features: [
      "2,500 risk reports per month",
      "API access with rotating keys",
      "Bulk batch processing",
      "Priority support + SLA",
    ],
    popular: true,
    cta_label: "Choose Pro",
  },
];

const FEATURE_LABELS: Record<string, string> = {
  risk_analysis: "AI risk analysis with deterministic ratios",
  pdf_extraction: "PDF text extraction from filings",
  bulk_export: "Bulk CSV / JSON export",
  api_access: "API access with personal keys",
};

interface ApiPlan {
  slug: string;
  name: string;
  description?: string | null;
  price_monthly_cents: number;
  price_yearly_cents: number;
  currency: string;
  features: Record<string, boolean>;
  limits: Record<string, number | null>;
  is_active: boolean;
}

function transformApiPlan(p: ApiPlan): Plan {
  const enabled = Object.entries(p.features ?? {})
    .filter(([, v]) => Boolean(v))
    .map(([k]) => FEATURE_LABELS[k] ?? k);
  const limits = p.limits ?? {};
  const searches = limits.searches_per_day;
  const lookups = limits.company_lookups_per_day;
  const risk = limits.risk_analyses_per_month;
  const features: string[] = [];
  if (searches != null) features.push(`${searches} searches/day`);
  if (lookups != null) features.push(`${lookups} company lookups/day`);
  if (risk != null && risk > 0) features.push(`${risk} risk analyses/month`);
  features.push(...enabled);
  return {
    id: p.slug,
    name: p.name,
    price_cents: p.price_monthly_cents,
    currency: (p.currency || "usd").toUpperCase(),
    interval: "month",
    features,
    popular: p.slug === "pro",
    cta_label: p.slug === "free" ? "Start free" : `Choose ${p.name}`,
  };
}

async function fetchPlans(): Promise<Plan[]> {
  const base =
    process.env.INTERNAL_API_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${base}/api/billing/plans`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return FALLBACK_PLANS;
    const data = (await res.json()) as ApiPlan[] | { plans?: ApiPlan[] };
    const raw = Array.isArray(data) ? data : data.plans ?? [];
    if (!raw.length) return FALLBACK_PLANS;
    return raw.map(transformApiPlan);
  } catch {
    return FALLBACK_PLANS;
  }
}

function currencySymbol(c?: string): string {
  return c === "EUR" ? "€" : c === "GBP" ? "£" : "$";
}

function priceDollars(plan: Plan): number {
  if (plan.price_cents === 0 || plan.price_cents === null) return 0;
  return plan.price_cents / 100;
}

export async function PricingTeaser() {
  const plans = await fetchPlans();
  const displayPlans = plans.slice(0, 3);

  return (
    <section
      id="pricing"
      className="relative border-b border-border-default py-24 md:py-32"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 mx-auto h-72 w-[60rem] max-w-full bg-aurora opacity-30 blur-3xl"
      />
      <div className="container relative">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-accent">
              Pricing
            </p>
            <h2 className="mt-4 font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default text-balance sm:text-6xl">
              Start free. Scale when you&apos;re ready.
            </h2>
            <p className="mt-5 text-lg text-fg-muted">
              Every plan ships with the same live registry data &mdash; you pay for
              volume, not for access.
            </p>
          </div>
        </Reveal>

        <Reveal stagger>
          <div className="mx-auto mt-16 grid max-w-5xl grid-cols-1 items-stretch gap-6 md:grid-cols-3">
            {displayPlans.map((plan) => {
              const isFree = plan.price_cents === 0 || plan.price_cents === null;
              const dollars = priceDollars(plan);
              return (
                <div
                  key={plan.id}
                  className={cn(
                    "relative flex flex-col rounded-2xl border p-7 transition-all",
                    plan.popular
                      ? "border-brand-primary/60 bg-bg-elevated shadow-depth-3 md:-translate-y-3 md:scale-[1.02]"
                      : "border-border-default/80 bg-bg-elevated/70 shadow-depth-1 hover:border-border-strong"
                  )}
                >
                  {plan.popular && (
                    <>
                      <div
                        aria-hidden
                        className="pointer-events-none absolute -inset-px rounded-2xl bg-gradient-to-br from-brand-primary/40 via-accent/20 to-brand-secondary/30 opacity-60 blur-xl"
                        style={{ zIndex: -1 }}
                      />
                      <Badge
                        variant="brand"
                        className="absolute -top-3 left-1/2 -translate-x-1/2 gap-1.5 px-3 py-1"
                      >
                        <Sparkles className="h-3 w-3" aria-hidden />
                        Most popular
                      </Badge>
                    </>
                  )}

                  <h3 className="font-display text-xl font-semibold tracking-tight text-fg-default">
                    {plan.name}
                  </h3>

                  <div className="mt-5 flex items-baseline gap-1.5">
                    {isFree ? (
                      <span className="font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default">
                        Free
                      </span>
                    ) : (
                      <>
                        <span className="font-display text-2xl font-semibold tracking-tight text-fg-muted">
                          {currencySymbol(plan.currency)}
                        </span>
                        <span className="font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default tabular-nums">
                          <AnimatedCounter
                            value={dollars}
                            duration={1.8}
                            decimals={Number.isInteger(dollars) ? 0 : 2}
                          />
                        </span>
                        <span className="text-sm text-fg-muted">
                          / {plan.interval ?? "month"}
                        </span>
                      </>
                    )}
                  </div>

                  <p className="mt-3 text-sm text-fg-muted">
                    {plan.popular
                      ? "For teams running daily underwriting at volume."
                      : isFree
                      ? "Everything you need to try Credyx, free forever."
                      : "Live financials and PDF exports for small credit teams."}
                  </p>

                  <ul className="mt-7 space-y-3 border-t border-border-default/70 pt-6">
                    {plan.features.map((f) => (
                      <li
                        key={f}
                        className="flex items-start gap-2.5 text-sm text-fg-default"
                      >
                        <span
                          className={cn(
                            "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full",
                            plan.popular
                              ? "bg-brand-primary/15 text-brand-primary"
                              : "bg-success/15 text-success"
                          )}
                          aria-hidden
                        >
                          <Check className="h-3 w-3" />
                        </span>
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>

                  <div className="mt-8 pt-2">
                    <Button
                      asChild
                      variant={plan.popular ? "primary" : "secondary"}
                      fullWidth
                    >
                      <Link href="/register">{plan.cta_label ?? "Get started"}</Link>
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </Reveal>

        <p className="mt-12 text-center text-sm text-fg-muted">
          Need an Enterprise plan, on-prem deployment or custom volume?{" "}
          <Link
            href="/contact"
            className="font-medium text-brand-primary underline-offset-4 hover:underline"
          >
            Talk to sales
          </Link>
          .
        </p>
      </div>
    </section>
  );
}
