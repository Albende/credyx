import Link from "next/link";
import { LogIn } from "lucide-react";
import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata = {
  title: "Create account - Credyx",
};

export default function RegisterPage() {
  return (
    <div className="space-y-8">
      <RegisterForm />
      <div className="flex items-center justify-center border-t border-border-default/60 pt-5 text-sm text-fg-muted">
        <span className="mr-1.5">Already have an account?</span>
        <Link
          href="/login"
          className="inline-flex items-center gap-1.5 font-medium text-brand-primary transition-colors hover:text-brand-primary/80"
        >
          <LogIn className="h-3.5 w-3.5" aria-hidden />
          Sign in
        </Link>
      </div>
    </div>
  );
}
