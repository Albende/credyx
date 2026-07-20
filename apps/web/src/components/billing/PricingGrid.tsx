"use client";

import { useMemo, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import type { Plan } from "@/lib/schemas/plan";
import { PlanCard } from "./PlanCard";

export function PricingGrid({ plans }: { plans: Plan[] }) {
  const [yearly, setYearly] = useState(false);
  const cycle = yearly ? "yearly" : "monthly";

  const sorted = useMemo(
    () =>
      [...plans]
        .filter((p) => p.is_active !== false)
        .sort((a, b) => a.price_monthly_cents - b.price_monthly_cents),
    [plans],
  );

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-center gap-3">
        <Label
          htmlFor="billing-cycle"
          className={!yearly ? "text-text" : "text-muted"}
        >
          Monthly
        </Label>
        <Switch
          id="billing-cycle"
          checked={yearly}
          onCheckedChange={setYearly}
          aria-label="Toggle yearly billing"
        />
        <Label
          htmlFor="billing-cycle"
          className={yearly ? "text-text" : "text-muted"}
        >
          Yearly
          <span className="ml-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-accent">
            Save 2 months
          </span>
        </Label>
      </div>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {sorted.map((plan) => (
          <PlanCard
            key={plan.slug}
            plan={plan}
            billingCycle={cycle}
            highlighted={Boolean(plan.highlighted) || plan.slug === "pro"}
          />
        ))}
      </div>
    </div>
  );
}
