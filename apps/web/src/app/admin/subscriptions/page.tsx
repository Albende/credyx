import { SubscriptionsTable } from "@/components/admin/subscriptions/SubscriptionsTable";
import { apiFetch } from "@/lib/api-client";
import type { AdminSubscription } from "@/components/admin/users/types";

async function fetchSubs(): Promise<{ subscriptions: AdminSubscription[]; total: number }> {
  try {
    return await apiFetch<{ subscriptions: AdminSubscription[]; total: number }>(
      "/api/admin/subscriptions",
      { serverSide: true },
    );
  } catch {
    return { subscriptions: [], total: 0 };
  }
}

export default async function SubscriptionsPage() {
  const data = await fetchSubs();
  return <SubscriptionsTable initialData={data} />;
}
