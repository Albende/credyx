"use client";
import { useState } from "react";
import { Pencil, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { PlanFormDialog } from "./PlanFormDialog";
import { SyncStripeButton, type SyncResult } from "./SyncStripeButton";
import { SyncStatusBadge } from "./SyncStatusBadge";
import type { AdminPlan } from "@/lib/schemas/plan";

function formatPrice(cents: number, currency: string) {
  if (cents === 0) return "Free";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);
}

function featureList(features: AdminPlan["features"]): string {
  return Object.entries(features)
    .filter(([, v]) => v)
    .map(([k]) => k.replace(/_/g, " "))
    .join(", ") || "—";
}

function limitsList(limits: AdminPlan["limits"]): string {
  return Object.entries(limits)
    .map(([k, v]) => `${k.split("_per_")[0]}: ${v}`)
    .join(", ");
}

export function PlansTable({ initialPlans }: { initialPlans: AdminPlan[] }) {
  const [plans, setPlans] = useState<AdminPlan[]>(initialPlans);
  const [editing, setEditing] = useState<AdminPlan | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  function applySync(slug: string, result: SyncResult) {
    setPlans((prev) =>
      prev.map((p) =>
        p.slug === slug
          ? {
              ...p,
              stripe_product_id: result.stripe_product_id,
              stripe_price_monthly_id: result.stripe_price_monthly_id,
              stripe_price_yearly_id: result.stripe_price_yearly_id,
            }
          : p,
      ),
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Plans</h1>
          <p className="mt-1 text-sm text-muted">Pricing, features, limits, and Stripe sync.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" /> New plan
        </Button>
      </div>

      <Card>
        {plans.length === 0 ? (
          <EmptyState title="No plans yet" description="Create your first plan to get started." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Slug</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Monthly</TableHead>
                <TableHead>Yearly</TableHead>
                <TableHead>Features</TableHead>
                <TableHead>Limits</TableHead>
                <TableHead>Stripe</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {plans.map((p) => (
                <TableRow key={p.slug}>
                  <TableCell className="font-mono text-xs">{p.slug}</TableCell>
                  <TableCell className="font-medium">
                    {p.name}
                    {!p.is_active ? <Badge variant="secondary" className="ml-2">inactive</Badge> : null}
                  </TableCell>
                  <TableCell className="tabular-nums">{formatPrice(p.price_monthly_cents, p.currency)}</TableCell>
                  <TableCell className="tabular-nums">{formatPrice(p.price_yearly_cents, p.currency)}</TableCell>
                  <TableCell className="text-xs text-muted">{featureList(p.features)}</TableCell>
                  <TableCell className="text-xs text-muted">{limitsList(p.limits)}</TableCell>
                  <TableCell>
                    <SyncStatusBadge
                      stripe_product_id={p.stripe_product_id ?? null}
                      monthly_synced={Boolean(p.stripe_price_monthly_id)}
                      yearly_synced={Boolean(p.stripe_price_yearly_id)}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="sm" onClick={() => setEditing(p)}>
                        <Pencil className="h-3 w-3" /> Edit
                      </Button>
                      <SyncStripeButton planSlug={p.slug} onSynced={(r) => applySync(p.slug, r)} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <PlanFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        plan={null}
        onSaved={(saved) => setPlans((prev) => [...prev, saved])}
      />
      <PlanFormDialog
        open={editing !== null}
        onOpenChange={(v) => !v && setEditing(null)}
        plan={editing}
        onSaved={(saved) => setPlans((prev) => prev.map((p) => (p.slug === saved.slug ? saved : p)))}
      />
    </div>
  );
}
