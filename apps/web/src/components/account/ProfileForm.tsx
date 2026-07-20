"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";
import { profileUpdateSchema, type ProfileUpdate, type User } from "@/lib/schemas/auth";

export function ProfileForm({ user }: { user: User }) {
  const [verifying, setVerifying] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);

  const form = useForm<ProfileUpdate>({
    resolver: zodResolver(profileUpdateSchema),
    defaultValues: {
      first_name: user.first_name || "",
      last_name: user.last_name || "",
    },
  });

  async function onSubmit(values: ProfileUpdate) {
    try {
      await apiFetch<User>("/api/auth/me", {
        method: "PATCH",
        body: JSON.stringify(values),
      });
      toast.success("Profile updated");
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to update profile";
      toast.error(detail);
    }
  }

  async function sendVerification() {
    setVerifying(true);
    try {
      await apiFetch<void>("/api/auth/send-verification", { method: "POST" });
      toast.success("Verification email sent");
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to send verification email";
      toast.error(detail);
    } finally {
      setVerifying(false);
    }
  }

  async function requestPasswordReset() {
    setChangingPassword(true);
    try {
      await apiFetch<void>("/api/auth/password-reset/request", {
        method: "POST",
        body: JSON.stringify({ email: user.email }),
      });
      toast.success("Password reset email sent");
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to send reset email";
      toast.error(detail);
    } finally {
      setChangingPassword(false);
    }
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Update your name as shown across Credyx.</CardDescription>
        </CardHeader>
        <form onSubmit={form.handleSubmit(onSubmit)}>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="first_name">First name</Label>
              <Input id="first_name" {...form.register("first_name")} />
              {form.formState.errors.first_name ? (
                <p className="text-xs text-bad">{form.formState.errors.first_name.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="last_name">Last name</Label>
              <Input id="last_name" {...form.register("last_name")} />
              {form.formState.errors.last_name ? (
                <p className="text-xs text-bad">{form.formState.errors.last_name.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <div className="flex items-center gap-2">
                <Input id="email" value={user.email} readOnly disabled />
                {user.is_verified ? (
                  <Badge variant="success">Verified</Badge>
                ) : (
                  <Button type="button" size="sm" variant="secondary" onClick={sendVerification} disabled={verifying}>
                    {verifying ? "Sending..." : "Verify"}
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? "Saving..." : "Save changes"}
            </Button>
          </CardFooter>
        </form>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>Request a password reset link sent to your email.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted">
            For security, password changes are handled via a one-time link sent to {user.email}.
          </p>
        </CardContent>
        <CardFooter>
          <Button type="button" variant="secondary" onClick={requestPasswordReset} disabled={changingPassword}>
            {changingPassword ? "Sending..." : "Send reset email"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
