"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormError } from "@/components/ui/form-error";
import { apiFetch, ApiError } from "@/lib/api-client";
import { resetSchema, type ResetInput } from "@/lib/schemas/auth";

export function ResetPasswordForm({ token }: { token: string }) {
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResetInput>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: "", password_confirm: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      await apiFetch("/api/auth/reset-password", {
        method: "POST",
        skipAuth: true,
        body: JSON.stringify({ token, password: values.password }),
      });
      toast.success("Password updated");
      setDone(true);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Reset failed";
      setSubmitError(message);
    }
  });

  if (done) {
    return (
      <div className="space-y-3 text-center">
        <h2 className="text-lg font-semibold">Password updated</h2>
        <p className="text-sm text-muted">
          You can now sign in with your new password.
        </p>
        <Link href="/login">
          <Button fullWidth>Continue to sign in</Button>
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="password">New password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          invalid={!!errors.password}
          {...register("password")}
        />
        <FormError message={errors.password?.message} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password_confirm">Confirm new password</Label>
        <Input
          id="password_confirm"
          type="password"
          autoComplete="new-password"
          invalid={!!errors.password_confirm}
          {...register("password_confirm")}
        />
        <FormError message={errors.password_confirm?.message} />
      </div>
      <FormError message={submitError} />
      <Button type="submit" fullWidth loading={isSubmitting}>
        Update password
      </Button>
    </form>
  );
}
