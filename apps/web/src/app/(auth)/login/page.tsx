import Link from "next/link";
import { Suspense } from "react";
import { KeyRound, UserPlus } from "lucide-react";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata = {
  title: "Sign in - Credyx",
};

export default function LoginPage() {
  return (
    <div className="space-y-8">
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
      <div className="flex items-center justify-between border-t border-border-default/60 pt-5 text-sm text-fg-muted">
        <Link
          href="/forgot-password"
          className="inline-flex items-center gap-1.5 transition-colors hover:text-fg-default"
        >
          <KeyRound className="h-3.5 w-3.5" aria-hidden />
          Forgot password?
        </Link>
        <Link
          href="/register"
          className="inline-flex items-center gap-1.5 font-medium text-brand-primary transition-colors hover:text-brand-primary/80"
        >
          <UserPlus className="h-3.5 w-3.5" aria-hidden />
          Create account
        </Link>
      </div>
    </div>
  );
}
