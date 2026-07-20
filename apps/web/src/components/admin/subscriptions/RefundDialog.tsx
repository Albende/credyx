"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
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

export function RefundDialog({
  subscriptionId,
  open,
  onOpenChange,
  onRefunded,
}: {
  subscriptionId: string | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onRefunded: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function refund() {
    if (!subscriptionId) return;
    const cents = Math.round(Number(amount) * 100);
    if (!Number.isFinite(cents) || cents <= 0) {
      toast.error("Enter a positive amount");
      return;
    }
    setBusy(true);
    try {
      await apiFetch<void>(`/api/admin/subscriptions/${subscriptionId}/refund`, {
        method: "POST",
        body: JSON.stringify({ amount_cents: cents, reason }),
      });
      toast.success("Refund issued");
      onRefunded();
      onOpenChange(false);
      setAmount("");
      setReason("");
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Refund failed";
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Refund</DialogTitle>
          <DialogDescription>Issue a refund through Stripe for this subscription's most recent invoice.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="amount">Amount</Label>
            <Input id="amount" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="49.00" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="reason">Reason (optional)</Label>
            <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={refund} disabled={busy}>
            {busy ? "Refunding..." : "Issue refund"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
