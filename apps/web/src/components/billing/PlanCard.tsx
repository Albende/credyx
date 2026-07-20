import Link from "next/link";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import type { Plan } from "@/lib/schemas/plan";
import { CheckoutButton } from "./CheckoutButton";

function formatPrice(cents: number, currency: string): string {
  if (cents === 0) return "Free";
  const amount = cents / 100;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

function featureList(plan: Plan): string[] {
  const items: string[] = [];
  const { features, limits } = plan;
  const f = features as Record<string, boolean | undefined>;
  if (f.risk_analysis) items.push("AI credit risk analysis");
  if (f.pdf_extraction) items.push("PDF filing text extraction");
  if (f.bulk_export) items.push("Bulk CSV export");
  if (f.api_access) items.push("API access");
  const l = limits as Record<string, number | null | undefined>;
  if (l.searches_per_day != null) {
    items.push(`${l.searches_per_day} searches / day`);
  }
  if (l.company_lookups_per_day != null) {
    items.push(`${l.company_lookups_per_day} company lookups / day`);
  }
  if (l.risk_analyses_per_month != null) {
    items.push(`${l.risk_analyses_per_month} risk analyses / month`);
  }
  return items;
}

export function PlanCard({
  plan,
  billingCycle,
  highlighted = false,
}: {
  plan: Plan;
  billingCycle: "monthly" | "yearly";
  highlighted?: boolean;
}) {
  const cents =
    billingCycle === "yearly"
      ? plan.price_yearly_cents
      : plan.price_monthly_cents;
  const isFree = plan.price_monthly_cents === 0 && plan.price_yearly_cents === 0;
  const periodLabel = billingCycle === "yearly" ? "/ year" : "/ month";
  const features = featureList(plan);

  return (
    <Card
      className={cn(
        "flex flex-col gap-6 p-6",
        highlighted && "border-accent ring-1 ring-accent/30 bg-surface",
      )}
    >
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">{plan.name}</h3>
          {highlighted ? (
            <span className="rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-accent">
              Most popular
            </span>
          ) : null}
        </div>
        {plan.description ? (
          <p className="text-sm text-muted">{plan.description}</p>
        ) : null}
      </div>

      <div>
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-semibold tracking-tight">
            {formatPrice(cents, plan.currency)}
          </span>
          {!isFree ? (
            <span className="text-sm text-muted">{periodLabel}</span>
          ) : null}
        </div>
      </div>

      <ul className="flex-1 space-y-2 text-sm">
        {features.map((f) => (
          <li key={f} className="flex items-start gap-2">
            <Check className="mt-0.5 h-4 w-4 text-accent" aria-hidden />
            <span>{f}</span>
          </li>
        ))}
      </ul>

      <div>
        {isFree ? (
          <Link href="/register" className="block">
            <Button variant="secondary" fullWidth>
              {plan.cta_label || "Get started"}
            </Button>
          </Link>
        ) : (
          <CheckoutButton
            planSlug={plan.slug}
            period={billingCycle}
            label={plan.cta_label || "Get started"}
            variant={highlighted ? "primary" : "secondary"}
          />
        )}
      </div>
    </Card>
  );
}
