import { Activity, Calendar, DollarSign, TrendingDown, TrendingUp, Users } from "lucide-react";
import { Stat } from "@/components/ui/stat";
import type { AdminMetrics } from "./types";

function formatMoney(cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

export function KpiGrid({ metrics }: { metrics: AdminMetrics }) {
  return (
    <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      <Stat label="Total users" value={metrics.total_users.toLocaleString()} icon={<Users className="h-4 w-4" />} />
      <Stat
        label="Active subs"
        value={metrics.active_subscriptions.toLocaleString()}
        icon={<Activity className="h-4 w-4" />}
      />
      <Stat
        label="MRR"
        value={formatMoney(metrics.mrr_cents, metrics.currency)}
        icon={<DollarSign className="h-4 w-4" />}
        hint="monthly recurring"
      />
      <Stat
        label="ARR"
        value={formatMoney(metrics.arr_cents, metrics.currency)}
        icon={<TrendingUp className="h-4 w-4" />}
        hint="annual run-rate"
      />
      <Stat
        label="Churn 30d"
        value={`${metrics.churn_30d_pct.toFixed(1)}%`}
        icon={<TrendingDown className="h-4 w-4" />}
      />
      <Stat label="DAU today" value={metrics.dau_today.toLocaleString()} icon={<Calendar className="h-4 w-4" />} />
    </div>
  );
}
