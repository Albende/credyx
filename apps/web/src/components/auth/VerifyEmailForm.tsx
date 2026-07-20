"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api-client";

type Status = "idle" | "verifying" | "ok" | "missing" | "error";

export function VerifyEmailForm() {
  const params = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string>("");
  const submitted = useRef(false);

  useEffect(() => {
    if (submitted.current) return;
    if (!token) {
      setStatus("missing");
      return;
    }
    submitted.current = true;
    setStatus("verifying");
    apiFetch("/api/auth/verify-email", {
      method: "POST",
      skipAuth: true,
      body: JSON.stringify({ token }),
    })
      .then(() => {
        setStatus("ok");
      })
      .catch((err: unknown) => {
        const m =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Verification failed";
        setMessage(m);
        setStatus("error");
      });
  }, [token]);

  if (status === "missing") {
    return (
      <div className="space-y-3 text-center">
        <p className="text-sm text-muted">
          This link is missing a verification token. Please use the link from
          your inbox.
        </p>
        <Link
          href="/login"
          className="inline-block text-sm text-accent hover:underline"
        >
          Return to sign in
        </Link>
      </div>
    );
  }

  if (status === "ok") {
    return (
      <div className="space-y-4 text-center">
        <h2 className="text-lg font-semibold">Email verified</h2>
        <p className="text-sm text-muted">
          Your account is active. You can now sign in.
        </p>
        <Link href="/login">
          <Button fullWidth>Continue to sign in</Button>
        </Link>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="space-y-3 text-center">
        <h2 className="text-lg font-semibold">Verification failed</h2>
        <p className="text-sm text-bad">{message}</p>
        <p className="text-xs text-muted">
          The link may have expired. Request a new one by signing in.
        </p>
        <Link
          href="/login"
          className="inline-block text-sm text-accent hover:underline"
        >
          Return to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3 text-center">
      <p className="text-sm text-muted">Verifying your email&hellip;</p>
    </div>
  );
}
