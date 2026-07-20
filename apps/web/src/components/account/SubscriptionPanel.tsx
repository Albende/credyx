"use client";
import { useState } from "react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";

export interface UsageEntry {
  key: string;
  label: string;
  used: number;
  limit: number;
  period: string;
}

export interface SubscriptionData {
  id: string;
  status: "active" | "trialing" | "past_due" | "canceled" | "incomplete";
  billing_period: "monthly" | "yearly";
  current_period_end: string;
  cancel_at_period_end: boolean;
  plan: {
    slug: string;
    name: string;
    limits: Record<string, number>;
  };
  usage?: UsageEntry[];
}

interface Props {
  subscription: SubscriptionData | null;
}

function formatDate(iso: string) {
  try {
    return format(new Date(iso), "PPP");
  } catch {
    return iso;
  }
}

export function SubscriptionPanel({ subscription }: Props) {
  const [openingPortal, setOpeningPortal] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  if (!subscription) {
    return (
      <EmptyState
        title="No active subscription"
        description="Pick a plan to unlock searches, risk analyses, and PDF extraction."
        action={
          <Button asChild>
            <a href="/pricing">View plans</a>
          </Button>
        }
      />
    );
  }

  async function openPortal() {
    setOpeningPortal(true);
    try {
      const data = await apiFetch<{ url: string }>("/api/billing/portal-session", { method: "POST" });
      window.location.href = data.url;
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Could not open Stripe portal";
      toast.error(detail);
      setOpeningPortal(false);
    }
  }

  async function cancelSubscription() {
    setCancelling(true);
    try {
      await apiFetch<void>("/api/billing/cancel", { method: "POST" });
      toast.success("Subscription scheduled for cancellation at period end");
      setConfirmingCancel(false);
      window.location.reload();
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to cancel";
      toast.error(detail);
    } finally {
      setCancelling(false);
    }
  }

  const usage =
    subscription.usage ??
    Object.entries(subscription.plan.limits).map(([key, limit]) => ({
      key,
      label: key.replace(/_/g, " "),
      used: 0,
      limit,
      period: key.includes("month") ? "this month" : "today",
    }));

  return (
    <div className="grid gap-6 md:grid-cols-3">
      <Card className="md:col-span-2">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle>{subscription.plan.name}</CardTitle>
              <CardDescription>
                Renews {formatDate(subscription.current_period_end)} ({subscription.billing_period})
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <Badge variant={subscription.status === "active" ? "success" : "warning"}>{subscription.status}</Badge>
              {subscription.cancel_at_period_end ? (
                <Badge variant="warning">Cancels at period end</Badge>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <h4 className="mb-3 text-xs uppercase tracking-wider text-muted">Usage</h4>
          <div className="space-y-3">
            {usage.map((u) => {
              const pct = u.limit > 0 ? Math.min(100, Math.round((u.used / u.limit) * 100)) : 0;
              return (
                <div key={u.key}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="capitalize">{u.label}</span>
                    <span className="text-muted">
                      {u.used} / {u.limit} {u.period}
                    </span>
                  </div>
                  <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-bg-overlay">
                    <div
                      className={`h-full ${pct > 80 ? "bg-bad" : pct > 50 ? "bg-warn" : "bg-accent"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
        <CardFooter className="gap-2">
          <Button onClick={openPortal} disabled={openingPortal}>
            {openingPortal ? "Opening..." : "Manage in Stripe Portal"}
          </Button>
          {!subscription.cancel_at_period_end ? (
            <Button variant="secondary" onClick={() => setConfirmingCancel(true)}>
              Cancel subscription
            </Button>
          ) : null}
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Plan limits</CardTitle>
          <CardDescription>Hard caps for the {subscription.plan.name} plan.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="space-y-2 text-sm">
            {Object.entries(subscription.plan.limits).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <dt className="capitalize text-muted">{k.replace(/_/g, " ")}</dt>
                <dd className="font-medium tabular-nums">{v.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Dialog open={confirmingCancel} onOpenChange={setConfirmingCancel}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel subscription?</DialogTitle>
            <DialogDescription>
              Your plan will remain active until {formatDate(subscription.current_period_end)}. You won't be charged
              again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setConfirmingCancel(false)} disabled={cancelling}>
              Keep subscription
            </Button>
            <Button variant="destructive" onClick={cancelSubscription} disabled={cancelling}>
              {cancelling ? "Cancelling..." : "Confirm cancel"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
