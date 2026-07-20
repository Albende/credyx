"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api-client";

interface CheckoutResponse {
  checkout_url: string;
}

export function CheckoutButton({
  planSlug,
  period,
  label = "Get started",
  variant = "primary",
}: {
  planSlug: string;
  period: "monthly" | "yearly";
  label?: string;
  variant?: "primary" | "secondary" | "outline";
}) {
  const [loading, setLoading] = useState(false);

  return (
    <Button
      loading={loading}
      variant={variant}
      fullWidth
      onClick={async () => {
        setLoading(true);
        try {
          const { checkout_url } = await apiFetch<CheckoutResponse>(
            "/api/billing/checkout-session",
            {
              method: "POST",
              body: JSON.stringify({
                plan_slug: planSlug,
                billing_period: period,
              }),
            },
          );
          window.location.href = checkout_url;
        } catch (err) {
          setLoading(false);
          const message =
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : "Checkout failed";
          toast.error(message);
        }
      }}
    >
      {label}
    </Button>
  );
}
