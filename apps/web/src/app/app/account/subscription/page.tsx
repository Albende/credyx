import { SubscriptionPanel, type SubscriptionData } from "@/components/account/SubscriptionPanel";
import { apiFetch, ApiError } from "@/lib/api-client";

async function fetchSubscription(): Promise<SubscriptionData | null> {
  try {
    return await apiFetch<SubscriptionData>("/api/billing/me/subscription", { serverSide: true });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 204)) {
      return null;
    }
    return null;
  }
}

export default async function SubscriptionPage() {
  const subscription = await fetchSubscription();
  return <SubscriptionPanel subscription={subscription} />;
}
