import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";

export const metadata = {
  title: "Reset password - Credyx",
};

export default function ForgotPasswordPage() {
  return (
    <div className="space-y-8">
      <ForgotPasswordForm />
      <div className="flex items-center justify-center border-t border-border-default/60 pt-5 text-sm text-fg-muted">
        <Link
          href="/login"
          className="inline-flex items-center gap-1.5 font-medium text-brand-primary transition-colors hover:text-brand-primary/80"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          Back to sign in
        </Link>
      </div>
    </div>
  );
}
