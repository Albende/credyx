"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, CreditCard, FileText, LogOut, Package, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Logo } from "@/components/ui/logo";
import { signOut } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import type { User } from "@/lib/schemas/auth";

const NAV = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/plans", label: "Plans", icon: Package },
  { href: "/admin/subscriptions", label: "Subscriptions", icon: CreditCard },
  { href: "/admin/audit-log", label: "Audit Log", icon: FileText },
  { href: "/admin/metrics", label: "Metrics", icon: BarChart3 },
] as const;

function initials(user: User): string {
  const f = user.first_name?.[0] || "";
  const l = user.last_name?.[0] || "";
  if (f || l) return `${f}${l}`.toUpperCase();
  return user.email.slice(0, 2).toUpperCase();
}

export function AdminShell({ user, children }: { user: User; children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-[calc(100vh-6rem)] -mx-6">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-border-default bg-bg-elevated/80 backdrop-blur-xl">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-40 [mask-image:linear-gradient(to_bottom,black,transparent)]"
        >
          <div className="texture-guilloche absolute inset-0 text-brand-primary/[0.06]" />
        </div>
        <div className="relative flex h-16 items-center justify-between gap-2 px-5 border-b border-border-default">
          <div className="flex items-center gap-2">
            <Logo href="/admin" />
            <span className="label rounded border border-border-default px-1.5 py-0.5 text-[0.6rem] text-fg-muted">admin</span>
          </div>
          <ThemeToggle />
        </div>
        <nav className="flex-1 space-y-1 p-3">
          <p className="label px-3 pb-1 pt-2">Administration</p>
          {NAV.map((item) => {
            const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition",
                  active ? "bg-brand-primary/10 text-brand-primary" : "text-fg-muted hover:bg-bg-overlay hover:text-fg-default",
                )}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-brand-primary" />
                )}
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-border-default p-3">
          <div className="mb-2 flex items-center gap-2 rounded-lg p-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-primary/15 text-xs font-medium text-brand-primary">
              {initials(user)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">
                {user.first_name || user.email.split("@")[0]}
              </div>
              <div className="truncate text-xs text-fg-muted">{user.email}</div>
            </div>
          </div>
          <Button variant="ghost" size="sm" className="w-full justify-start text-fg-muted" onClick={() => signOut()}>
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
        </div>
      </aside>
      <main className="flex-1 p-8">{children}</main>
    </div>
  );
}
