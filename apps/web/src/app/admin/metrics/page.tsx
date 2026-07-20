import { KpiGrid } from "@/components/admin/metrics/KpiGrid";
import { MrrChart } from "@/components/admin/metrics/MrrChart";
import { SignupsChart } from "@/components/admin/metrics/SignupsChart";
import { apiFetch } from "@/lib/api-client";
import type { AdminMetrics } from "@/components/admin/metrics/types";

async function fetchMetrics(): Promise<AdminMetrics> {
  try {
    return await apiFetch<AdminMetrics>("/api/admin/metrics", { serverSide: true });
  } catch {
    return {
      total_users: 0,
      active_subscriptions: 0,
      mrr_cents: 0,
      arr_cents: 0,
      churn_30d_pct: 0,
      dau_today: 0,
      currency: "usd",
    };
  }
}

export default async function MetricsPage() {
  const metrics = await fetchMetrics();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Metrics</h1>
        <p className="mt-1 text-sm text-muted">Key business indicators.</p>
      </div>
      <KpiGrid metrics={metrics} />
      <div className="grid gap-4 lg:grid-cols-2">
        <MrrChart />
        <SignupsChart />
      </div>
    </div>
  );
}
