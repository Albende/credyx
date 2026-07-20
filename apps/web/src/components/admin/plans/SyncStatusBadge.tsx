import { Badge } from "@/components/ui/badge";

export interface SyncStatusBadgeProps {
  stripe_product_id: string | null | undefined;
  monthly_synced: boolean;
  yearly_synced: boolean;
}

export function SyncStatusBadge({ stripe_product_id, monthly_synced, yearly_synced }: SyncStatusBadgeProps) {
  if (!stripe_product_id) return <Badge variant="secondary">Not synced</Badge>;
  if (monthly_synced && yearly_synced) return <Badge variant="success">Synced</Badge>;
  return <Badge variant="warning">Out of sync</Badge>;
}
