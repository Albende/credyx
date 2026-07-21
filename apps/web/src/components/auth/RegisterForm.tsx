"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import Link from "next/link";
import { AlertCircle, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormError } from "@/components/ui/form-error";
import { apiFetch, ApiError } from "@/lib/api-client";
import { registerSchema, type RegisterInput } from "@/lib/schemas/auth";
import { humanizeError } from "@/lib/humanize-error";

export function RegisterForm() {
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      email: "",
      first_name: "",
      last_name: "",
      password: "",
      password_confirm: "",
      accept_tos: false,
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      const created = await apiFetch<{ email_verified: boolean; role: string }>(
        "/api/auth/register",
        {
          method: "POST",
          skipAuth: true,
          body: JSON.stringify({
            email: values.email,
            first_name: values.first_name,
            last_name: values.last_name,
            password: values.password,
          }),
        },
      );

      if (created.email_verified) {
        const loginRes = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ email: values.email, password: values.password }),
        });
        if (loginRes.ok) {
          toast.success("Welcome to Credyx.");
          window.location.href = created.role === "admin" ? "/admin/users" : "/app";
          return;
        }
      }
      toast.success("Account created. Check your inbox.");
      setSubmittedEmail(values.email);
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? ((err.body as { detail?: string } | undefined)?.detail ?? err.message)
          : err instanceof Error
            ? err.message
            : null;
      setSubmitError(humanizeError(detail, "Couldn't create your account. Please try again."));
    }
  });

  if (submittedEmail) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-full border border-success/30 bg-success/10 text-success">
          <MailCheck className="h-5 w-5" aria-hidden />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-h2 tracking-tight text-fg-default">
            Check your email
          </h2>
          <p className="text-sm text-fg-muted">
            We sent a verification link to{" "}
            <span className="font-medium text-fg-default">{submittedEmail}</span>.
            Click it to activate your account.
          </p>
        </div>
        <p className="text-xs text-fg-subtle">
          Didn&apos;t get it? Check your spam folder or{" "}
          <Link href="/login" className="text-brand-primary hover:underline">
            return to sign in
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-7">
      <header className="space-y-2">
        <h2 className="font-display text-h2 tracking-tight text-fg-default">
          Create your account
        </h2>
        <p className="text-sm text-fg-muted">
          Start running credit risk analyses in minutes.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="first_name" className="text-sm font-medium">
              First name
            </Label>
            <Input
              id="first_name"
              autoComplete="given-name"
              placeholder="Jane"
              invalid={!!errors.first_name}
              className="h-11 rounded-lg border-border-default/80 bg-bg-base text-[0.9375rem]"
              {...register("first_name")}
            />
            <FormError message={errors.first_name?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="last_name" className="text-sm font-medium">
              Last name
            </Label>
            <Input
              id="last_name"
              autoComplete="family-name"
              placeholder="Doe"
              invalid={!!errors.last_name}
              className="h-11 rounded-lg border-border-default/80 bg-bg-base text-[0.9375rem]"
              {...register("last_name")}
            />
            <FormError message={errors.last_name?.message} />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="email" className="text-sm font-medium">
            Work email
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
            autoComplete="new-password"
            placeholder="At least 8 characters"
            invalid={!!errors.password}
            className="h-11 rounded-lg border-border-default/80 bg-bg-base text-[0.9375rem]"
            {...register("password")}
          />
          <FormError message={errors.password?.message} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password_confirm" className="text-sm font-medium">
            Confirm password
          </Label>
          <Input
            id="password_confirm"
            type="password"
            autoComplete="new-password"
            placeholder="Repeat your password"
            invalid={!!errors.password_confirm}
            className="h-11 rounded-lg border-border-default/80 bg-bg-base text-[0.9375rem]"
            {...register("password_confirm")}
          />
          <FormError message={errors.password_confirm?.message} />
        </div>

        <label className="flex items-start gap-2.5 text-xs text-fg-muted">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-border-default bg-bg-base accent-[hsl(var(--color-brand-primary))]"
            {...register("accept_tos")}
          />
          <span className="leading-snug">
            I agree to the{" "}
            <Link href="/terms" className="text-brand-primary hover:underline">
              Terms of Service
            </Link>{" "}
            and{" "}
            <Link href="/privacy" className="text-brand-primary hover:underline">
              Privacy Policy
            </Link>
            .
          </span>
        </label>
        <FormError message={errors.accept_tos?.message} />

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
          Create account
        </Button>
      </form>
    </div>
  );
}
