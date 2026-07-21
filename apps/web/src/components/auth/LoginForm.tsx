"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormError } from "@/components/ui/form-error";
import { loginSchema, type LoginInput } from "@/lib/schemas/auth";
import { humanizeError } from "@/lib/humanize-error";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          humanizeError(
            (body as { detail?: string }).detail,
            "That email and password don't match. Please try again.",
          ),
        );
      }
      toast.success("Welcome back");
      const next = params.get("next") || "/app";
      router.push(next);
      router.refresh();
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Couldn't sign you in. Please try again.",
      );
    }
  });

  return (
    <div className="space-y-7">
      <header className="space-y-2">
        <h2 className="font-display text-h2 tracking-tight text-fg-default">
          Welcome back
        </h2>
        <p className="text-sm text-fg-muted">
          Sign in to pick up where you left off.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        <div className="space-y-2">
          <Label htmlFor="email" className="text-sm font-medium">
            Email
          </Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            invalid={!!errors.email}
            className="h-11 rounded-lg border-border-default/80 bg-bg-base text-[0.9375rem]"
            {...register("email")}
          />
          <FormError message={errors.email?.message} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password" className="text-sm font-medium">
            Password
          </Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
            invalid={!!errors.password}
            className="h-11 rounded-lg border-border-default/80 bg-bg-base text-[0.9375rem]"
            {...register("password")}
          />
          <FormError message={errors.password?.message} />
        </div>

        {submitError ? (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger/10 px-3.5 py-3 text-sm text-danger"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="leading-snug">{submitError}</span>
          </div>
        ) : null}

        <Button
          type="submit"
          fullWidth
          loading={isSubmitting}
          size="lg"
          className="h-11 rounded-lg font-semibold shadow-elev-1 transition-transform duration-150 ease-spring active:scale-[0.98]"
        >
          Sign in
        </Button>
      </form>
    </div>
  );
}
