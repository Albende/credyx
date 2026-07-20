"use client";
import { useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
import { planSchema, type Plan, type AdminPlan } from "@/lib/schemas/plan";

const FEATURE_KEYS = ["risk_analysis", "pdf_extraction", "bulk_export", "api_access"] as const;
const LIMIT_KEYS = ["searches_per_day", "company_lookups_per_day", "risk_analyses_per_month", "financial_lookups_per_month"] as const;

const DEFAULT_PLAN: Plan = {
  slug: "",
  name: "",
  description: "",
  price_monthly_cents: 0,
  price_yearly_cents: 0,
  currency: "usd",
  is_active: true,
  features: { risk_analysis: false, pdf_extraction: false, bulk_export: false, api_access: false },
  limits: { searches_per_day: 0, company_lookups_per_day: 0, risk_analyses_per_month: 0, financial_lookups_per_month: 0 },
};

export function PlanFormDialog({
  open,
  onOpenChange,
  plan,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  plan: AdminPlan | null;
  onSaved: (plan: AdminPlan) => void;
}) {
  const isEdit = plan !== null;
  const form = useForm<Plan>({
    resolver: zodResolver(planSchema),
    defaultValues: plan ?? DEFAULT_PLAN,
  });

  useEffect(() => {
    form.reset(plan ?? DEFAULT_PLAN);
  }, [plan, open]);

  async function onSubmit(values: Plan) {
    try {
      const saved = isEdit
        ? await apiFetch<AdminPlan>(`/api/admin/plans/${values.slug}`, {
            method: "PATCH",
            body: JSON.stringify(values),
          })
        : await apiFetch<AdminPlan>("/api/admin/plans", {
            method: "POST",
            body: JSON.stringify(values),
          });
      toast.success(isEdit ? "Plan updated" : "Plan created");
      onSaved(saved);
      onOpenChange(false);
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Save failed";
      toast.error(detail);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${plan?.name}` : "New plan"}</DialogTitle>
          <DialogDescription>
            Define pricing, feature flags, and per-period limits. Sync to Stripe after saving.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="slug">Slug</Label>
              <Input id="slug" {...form.register("slug")} disabled={isEdit} placeholder="pro" />
              {form.formState.errors.slug ? (
                <p className="text-xs text-bad">{form.formState.errors.slug.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="name">Name</Label>
              <Input id="name" {...form.register("name")} placeholder="Pro" />
              {form.formState.errors.name ? (
                <p className="text-xs text-bad">{form.formState.errors.name.message}</p>
              ) : null}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="description">Description</Label>
            <Textarea id="description" rows={2} {...form.register("description")} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="monthly">Monthly (cents)</Label>
              <Input
                id="monthly"
                type="number"
                min={0}
                {...form.register("price_monthly_cents", { valueAsNumber: true })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="yearly">Yearly (cents)</Label>
              <Input
                id="yearly"
                type="number"
                min={0}
                {...form.register("price_yearly_cents", { valueAsNumber: true })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Currency</Label>
              <Controller
                control={form.control}
                name="currency"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="usd">USD</SelectItem>
                      <SelectItem value="eur">EUR</SelectItem>
                      <SelectItem value="gbp">GBP</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          </div>

          <Controller
            control={form.control}
            name="is_active"
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={field.value} onCheckedChange={field.onChange} />
                Active (visible on pricing page)
              </label>
            )}
          />

          <div>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted">Features</h4>
            <div className="grid grid-cols-2 gap-2">
              {FEATURE_KEYS.map((k) => (
                <Controller
                  key={k}
                  control={form.control}
                  name={`features.${k}` as const}
                  render={({ field }) => (
                    <label className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                      <span className="capitalize">{k.replace(/_/g, " ")}</span>
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    </label>
                  )}
                />
              ))}
            </div>
          </div>

          <div>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted">Limits</h4>
            <div className="grid grid-cols-2 gap-3">
              {LIMIT_KEYS.map((k) => (
                <div key={k} className="space-y-1.5">
                  <Label htmlFor={k} className="capitalize">
                    {k.replace(/_/g, " ")}
                  </Label>
                  <Input
                    id={k}
                    type="number"
                    min={0}
                    {...form.register(`limits.${k}` as const, { valueAsNumber: true })}
                  />
                </div>
              ))}
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? "Saving..." : isEdit ? "Save changes" : "Create plan"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
