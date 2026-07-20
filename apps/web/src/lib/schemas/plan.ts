import { z } from "zod";

export const planFeaturesSchema = z.object({
  risk_analysis: z.boolean().optional(),
  pdf_extraction: z.boolean().optional(),
  bulk_export: z.boolean().optional(),
  api_access: z.boolean().optional(),
});

export const planLimitsSchema = z.object({
  searches_per_day: z.number().nullable().optional(),
  company_lookups_per_day: z.number().nullable().optional(),
  risk_analyses_per_month: z.number().nullable().optional(),
});

export const planSchema = z.object({
  id: z.string().optional(),
  slug: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  price_monthly_cents: z.number().int().nonnegative(),
  price_yearly_cents: z.number().int().nonnegative(),
  currency: z.string().default("EUR"),
  features: planFeaturesSchema.passthrough(),
  limits: planLimitsSchema.passthrough(),
  is_active: z.boolean().default(true),
  highlighted: z.boolean().optional(),
  cta_label: z.string().optional(),
});

export type PlanFeatures = z.infer<typeof planFeaturesSchema>;
export type PlanLimits = z.infer<typeof planLimitsSchema>;
export type Plan = z.infer<typeof planSchema>;

// Admin view of a plan — includes Stripe IDs that are hidden from public plan responses.
export const adminPlanSchema = planSchema.extend({
  stripe_product_id: z.string().nullable().optional(),
  stripe_price_monthly_id: z.string().nullable().optional(),
  stripe_price_yearly_id: z.string().nullable().optional(),
});
export type AdminPlan = z.infer<typeof adminPlanSchema>;

export const plansResponseSchema = z.object({
  plans: z.array(planSchema),
});

export type PlansResponse = z.infer<typeof plansResponseSchema>;
