"use client";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";
import type { AdminPlan } from "@/lib/schemas/plan";

const grantSchema = z.object({
  plan_slug: z.string().min(1, "Required"),
  duration_days: z.coerce.number().int().min(1).max(3650),
  reason: z.string().min(3, "Provide a short reason"),
});
type GrantValues = z.infer<typeof grantSchema>;

export function GrantPlanForm({
  userId,
  onSuccess,
}: {
  userId: string;
  onSuccess: () => void;
}) {
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const form = useForm<GrantValues>({
    resolver: zodResolver(grantSchema),
    defaultValues: { plan_slug: "", duration_days: 30, reason: "" },
  });

  useEffect(() => {
    apiFetch<{ plans: AdminPlan[] }>("/api/admin/plans")
      .then((r) => setPlans(r.plans ?? []))
      .catch(() => setPlans([]));
  }, []);

  async function onSubmit(values: GrantValues) {
    try {
      await apiFetch<void>(`/api/admin/users/${userId}/grant-plan`, {
        method: "POST",
        body: JSON.stringify(values),
      });
      toast.success("Plan granted");
      onSuccess();
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to grant plan";
      toast.error(detail);
    }
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
      <div className="space-y-1.5">
        <Label>Plan</Label>
        <Select value={form.watch("plan_slug")} onValueChange={(v) => form.setValue("plan_slug", v, { shouldValidate: true })}>
          <SelectTrigger>
            <SelectValue placeholder="Select a plan" />
          </SelectTrigger>
          <SelectContent>
            {plans.map((p) => (
              <SelectItem key={p.slug} value={p.slug}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {form.formState.errors.plan_slug ? (
          <p className="text-xs text-bad">{form.formState.errors.plan_slug.message}</p>
        ) : null}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="duration_days">Duration (days)</Label>
        <Input id="duration_days" type="number" min={1} {...form.register("duration_days", { valueAsNumber: true })} />
        {form.formState.errors.duration_days ? (
          <p className="text-xs text-bad">{form.formState.errors.duration_days.message}</p>
        ) : null}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="reason">Reason</Label>
        <Textarea id="reason" rows={3} {...form.register("reason")} placeholder="Comped for partner trial." />
        {form.formState.errors.reason ? (
          <p className="text-xs text-bad">{form.formState.errors.reason.message}</p>
        ) : null}
      </div>
      <Button type="submit" disabled={form.formState.isSubmitting}>
        {form.formState.isSubmitting ? "Granting..." : "Grant plan"}
      </Button>
    </form>
  );
}
