import { PlansTable } from "@/components/admin/plans/PlansTable";
import { apiFetch } from "@/lib/api-client";
import type { AdminPlan } from "@/lib/schemas/plan";

async function fetchPlans(): Promise<AdminPlan[]> {
  try {
    const data = await apiFetch<{ plans: AdminPlan[] }>("/api/admin/plans", { serverSide: true });
    return data.plans ?? [];
  } catch {
    return [];
  }
}

export default async function PlansPage() {
  const plans = await fetchPlans();
  return <PlansTable initialPlans={plans} />;
}
