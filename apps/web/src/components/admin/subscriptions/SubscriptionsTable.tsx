"use client";
import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { CancelSubscriptionDialog } from "./CancelSubscriptionDialog";
import { RefundDialog } from "./RefundDialog";
import type { AdminSubscription } from "../users/types";

const STATUS_OPTIONS = ["all", "active", "trialing", "past_due", "canceled"] as const;
type Status = (typeof STATUS_OPTIONS)[number];

function formatDate(iso: string) {
  try {
    return format(new Date(iso), "PP");
  } catch {
    return iso;
  }
}

interface ListResponse {
  subscriptions: AdminSubscription[];
  total: number;
}

export function SubscriptionsTable({ initialData }: { initialData: ListResponse }) {
  const [data, setData] = useState<ListResponse>(initialData);
  const [status, setStatus] = useState<Status>("all");
  const [cancelTarget, setCancelTarget] = useState<string | null>(null);
  const [refundTarget, setRefundTarget] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (status !== "all") params.set("status", status);
    apiFetch<ListResponse>(`/api/admin/subscriptions?${params.toString()}`)
      .then(setData)
      .catch(() => undefined);
  }, [status]);

  function refresh() {
    const params = new URLSearchParams();
    if (status !== "all") params.set("status", status);
    apiFetch<ListResponse>(`/api/admin/subscriptions?${params.toString()}`).then(setData).catch(() => undefined);
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Subscriptions</h1>
        <p className="mt-1 text-sm text-muted">All paid subscriptions across users.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={cn(
              "rounded-full border border-border px-3 py-1 text-xs capitalize transition",
              status === s ? "bg-accent text-fg-inverted border-transparent" : "text-muted hover:bg-bg-overlay",
            )}
          >
            {s}
          </button>
        ))}
      </div>

      <Card>
        {data.subscriptions.length === 0 ? (
          <EmptyState title="No subscriptions" description="No subscriptions match the current filter." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Period</TableHead>
                <TableHead>Renews</TableHead>
                <TableHead>Granted</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.subscriptions.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.user?.email ?? "—"}</TableCell>
                  <TableCell>{s.plan.name}</TableCell>
                  <TableCell>
                    <Badge variant={s.status === "active" ? "success" : s.status === "past_due" ? "destructive" : "warning"}>
                      {s.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="capitalize">{s.billing_period}</TableCell>
                  <TableCell className="text-muted">{formatDate(s.current_period_end)}</TableCell>
                  <TableCell>
                    {s.granted_by_admin_id ? <Badge variant="warning">comped</Badge> : <span className="text-muted">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button size="sm" variant="ghost" onClick={() => setRefundTarget(s.id)}>
                        Refund
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setCancelTarget(s.id)}>
                        Cancel
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <CancelSubscriptionDialog
        subscriptionId={cancelTarget}
        open={cancelTarget !== null}
        onOpenChange={(v) => !v && setCancelTarget(null)}
        onCancelled={refresh}
      />
      <RefundDialog
        subscriptionId={refundTarget}
        open={refundTarget !== null}
        onOpenChange={(v) => !v && setRefundTarget(null)}
        onRefunded={refresh}
      />
    </div>
  );
}
