"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";

export function CancelSubscriptionDialog({
  subscriptionId,
  open,
  onOpenChange,
  onCancelled,
}: {
  subscriptionId: string | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCancelled: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function cancel() {
    if (!subscriptionId) return;
    setBusy(true);
    try {
      await apiFetch<void>(`/api/admin/subscriptions/${subscriptionId}/cancel`, { method: "POST" });
      toast.success("Subscription cancelled");
      onCancelled();
      onOpenChange(false);
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Cancel failed";
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cancel this subscription?</DialogTitle>
          <DialogDescription>This will end paid access at the end of the current billing period.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Keep
          </Button>
          <Button variant="destructive" onClick={cancel} disabled={busy}>
            {busy ? "Cancelling..." : "Cancel subscription"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
