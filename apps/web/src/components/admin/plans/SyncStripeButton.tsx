"use client";
import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";

export interface SyncResult {
  stripe_product_id: string | null;
  stripe_price_monthly_id: string | null;
  stripe_price_yearly_id: string | null;
}

export function SyncStripeButton({
  planSlug,
  onSynced,
}: {
  planSlug: string;
  onSynced?: (result: SyncResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);

  async function sync() {
    setBusy(true);
    try {
      const res = await apiFetch<SyncResult>(`/api/admin/plans/${planSlug}/sync-stripe`, { method: "POST" });
      setResult(res);
      onSynced?.(res);
      toast.success(`Synced ${planSlug} with Stripe`);
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Sync failed";
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <Button size="sm" variant="secondary" onClick={sync} disabled={busy}>
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        Sync
      </Button>
      {result ? (
        <div className="text-[10px] text-muted font-mono">
          {result.stripe_product_id ? `prod ${result.stripe_product_id.slice(0, 14)}…` : null}
        </div>
      ) : null}
    </div>
  );
}
