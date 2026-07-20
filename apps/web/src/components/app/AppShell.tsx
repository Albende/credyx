"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Globe,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/ui/logo";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { signOut } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import type { Session } from "@/lib/auth";

const NAV = [
  { href: "/app", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/app/search", label: "Search", icon: Search },
  { href: "/app/coverage", label: "Coverage", icon: Globe },
  { href: "/app/account", label: "Account", icon: Settings },
] as const;

function initials(user: Session): string {
  const f = user.first_name?.[0] || "";
  const l = user.last_name?.[0] || "";
  if (f || l) return `${f}${l}`.toUpperCase();
  return user.email.slice(0, 2).toUpperCase();
}

// Plan usage mini-chart values (decorative — would be wired to live quotas)
const USAGE_BARS = [0.35, 0.55, 0.4, 0.7, 0.5, 0.85, 0.62];

export function AppShell({ user, children }: { user: Session; children: React.ReactNode }) {
  const pathname = usePathname();
  const used = 3;
  const quota = 10;
  const pct = Math.min(100, Math.round((used / quota) * 100));

  return (
    <div className="relative flex min-h-screen bg-bg-base">
      {/* Ambient page glow behind the shell */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 opacity-60"
        style={{
          background:
            "radial-gradient(900px circle at 8% 0%, hsl(var(--color-brand-primary) / 0.10), transparent 55%), radial-gradient(700px circle at 100% 100%, hsl(var(--color-accent) / 0.08), transparent 55%)",
        }}
      />

      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-border-default/70 bg-bg-elevated/55 backdrop-blur-2xl">
        {/* Inner top highlight */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent"
        />

        {/* Engraved guilloché wash down the sidebar */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-48 [mask-image:linear-gradient(to_bottom,black,transparent)]"
        >
          <div className="texture-guilloche absolute inset-0 text-brand-primary/[0.06]" />
        </div>

        {/* Brand mark */}
        <div className="relative flex h-16 items-center justify-between gap-2 border-b border-border-default/60 px-5">
          <Logo href="/app" />
          <ThemeToggle />
        </div>

        {/* Nav */}
        <nav className="relative flex-1 space-y-0.5 p-3">
          <p className="px-3 pb-1.5 pt-2 font-mono text-[0.62rem] font-medium uppercase tracking-[0.18em] text-fg-subtle">
            Workspace
          </p>
          {NAV.map((item) => {
            const isExact = "exact" in item && item.exact;
            const active = isExact
              ? pathname === item.href
              : pathname === item.href || pathname?.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group relative flex items-center gap-3 overflow-hidden rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-brand-primary/12 text-brand-primary"
                    : "text-fg-muted hover:text-fg-default",
                )}
              >
                {/* Hover spotlight */}
                <span
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300",
                    !active && "group-hover:opacity-100",
                  )}
                  style={{
                    background:
                      "radial-gradient(220px circle at var(--mx, 50%) 50%, hsl(var(--color-brand-primary) / 0.10), transparent 70%)",
                  }}
                />
                <span
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute inset-0 rounded-lg border border-transparent transition-colors",
                    !active && "group-hover:border-border-default/80 group-hover:bg-bg-overlay/40",
                  )}
                />
                {active && (
                  <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-brand-primary shadow-[0_0_10px_hsl(var(--color-brand-primary)/0.6)]" />
                )}
                <Icon className="relative h-4 w-4" />
                <span className="relative">{item.label}</span>
              </Link>
            );
          })}

          {user.role === "admin" && (
            <Link
              href="/admin"
              className="group relative mt-3 flex items-center gap-3 overflow-hidden rounded-lg px-3 py-2 text-sm font-medium text-fg-muted transition-colors hover:text-fg-default"
            >
              <span
                aria-hidden
                className="pointer-events-none absolute inset-0 rounded-lg border border-transparent transition-colors group-hover:border-border-default/80 group-hover:bg-bg-overlay/40"
              />
              <ShieldCheck className="relative h-4 w-4" />
              <span className="relative">Admin panel</span>
            </Link>
          )}
        </nav>

        {/* Footer: plan-usage mini-chart + identity + sign out */}
        <div className="relative border-t border-border-default/60 p-3">
          <Link
            href="/app/account/subscription"
            className="group relative mb-3 block overflow-hidden rounded-xl border border-border-default/70 bg-bg-overlay/60 p-3 transition hover:border-brand-primary/40"
          >
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
              style={{
                background:
                  "radial-gradient(280px circle at 0% 0%, hsl(var(--color-brand-primary) / 0.18), transparent 60%)",
              }}
            />
            <div className="relative mb-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3 w-3 text-brand-primary" />
                <span className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-fg-subtle">
                  Free plan
                </span>
              </div>
              <span className="text-[10px] font-medium text-fg-muted tabular-nums">
                {used}/{quota}
              </span>
            </div>
            {/* Mini-bar usage chart */}
            <div className="relative flex h-7 items-end gap-[3px]">
              {USAGE_BARS.map((h, i) => (
                <span
                  key={i}
                  className="flex-1 rounded-sm bg-gradient-to-t from-brand-primary/30 to-brand-primary/80"
                  style={{ height: `${Math.round(h * 100)}%` }}
                />
              ))}
            </div>
            {/* Quota track */}
            <div className="relative mt-2 h-1 overflow-hidden rounded-full bg-bg-inset">
              <span
                className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-brand-primary to-accent"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="relative mt-1.5 text-[10px] text-fg-muted">
              Upgrade for unlimited reports
            </div>
          </Link>

          <div className="mb-2 flex items-center gap-2 rounded-lg p-1.5">
            <div className="relative h-9 w-9 shrink-0 overflow-hidden rounded-full">
              <span
                aria-hidden
                className="absolute inset-0"
                style={{
                  background:
                    "linear-gradient(135deg, hsl(var(--color-brand-primary) / 0.25), hsl(var(--color-accent) / 0.25))",
                }}
              />
              <span className="relative z-10 grid h-full w-full place-items-center text-xs font-semibold text-brand-primary">
                {initials(user)}
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">
                {user.first_name
                  ? `${user.first_name} ${user.last_name ?? ""}`.trim()
                  : user.email.split("@")[0]}
              </div>
              <div className="truncate text-xs text-fg-muted">{user.email}</div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-fg-muted hover:text-fg-default"
            onClick={() => signOut()}
          >
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
        </div>
      </aside>

      <main className="relative flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-7xl px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
