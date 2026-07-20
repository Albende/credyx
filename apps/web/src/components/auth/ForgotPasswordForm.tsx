"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormError } from "@/components/ui/form-error";
import { apiFetch } from "@/lib/api-client";
import { forgotSchema, type ForgotInput } from "@/lib/schemas/auth";

export function ForgotPasswordForm() {
  const [done, setDone] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ForgotInput>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    await apiFetch("/api/auth/forgot-password", {
      method: "POST",
      skipAuth: true,
      body: JSON.stringify(values),
    }).catch(() => undefined);
    setDone(true);
  });

  if (done) {
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
            If an account exists for that address, we sent a password reset
            link.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-7">
      <header className="space-y-2">
        <h2 className="font-display text-h2 tracking-tight text-fg-default">
          Forgot your password?
        </h2>
        <p className="text-sm text-fg-muted">
          Enter your email and we&apos;ll send a link to choose a new one.
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

        <Button
          type="submit"
          fullWidth
          loading={isSubmitting}
          size="lg"
          className="h-11 rounded-lg font-semibold shadow-elev-1 transition-transform duration-150 ease-spring active:scale-[0.98]"
        >
          Send reset link
        </Button>
      </form>
    </div>
  );
}
