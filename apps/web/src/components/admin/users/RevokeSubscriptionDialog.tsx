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

export function RevokeSubscriptionDialog({
  userId,
  open,
  onOpenChange,
  onRevoked,
}: {
  userId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onRevoked: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function revoke() {
    setBusy(true);
    try {
      await apiFetch<void>(`/api/admin/users/${userId}/revoke-subscription`, { method: "POST" });
      toast.success("Subscription revoked");
      onRevoked();
      onOpenChange(false);
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to revoke";
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revoke this subscription?</DialogTitle>
          <DialogDescription>The user loses paid access immediately. This is logged in the audit trail.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={revoke} disabled={busy}>
            {busy ? "Revoking..." : "Revoke"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
