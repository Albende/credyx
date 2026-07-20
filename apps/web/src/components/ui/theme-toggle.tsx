"use client";

import * as React from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown";
import { useTheme, type ThemeSelection } from "@/lib/use-theme";
import { cn } from "@/lib/cn";

const OPTIONS: {
  value: ThemeSelection;
  label: string;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { value: "system", label: "System", hint: "AUTO", icon: Monitor },
  { value: "light", label: "Light", hint: "BOND", icon: Sun },
  { value: "dark", label: "Dark", hint: "VAULT", icon: Moon },
];

export function ThemeToggle({ className }: { className?: string }) {
  const { selection, effective, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const TriggerIcon = !mounted
    ? Monitor
    : selection === "system"
      ? Monitor
      : selection === "dark"
        ? Moon
        : Sun;

  const label = !mounted
    ? "Theme"
    : selection === "system"
      ? `Theme: system (${effective})`
      : `Theme: ${selection}`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={label}
        title={label}
        className={cn(
          "group relative inline-flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg border border-border-default bg-bg-elevated text-fg-muted transition-colors hover:border-border-strong hover:text-fg-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-2 focus-visible:ring-offset-bg-base",
          className,
        )}
      >
        {/* Shade-pull hint: gilt edge drops in on hover */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-1 top-0 h-px -translate-y-full bg-gradient-to-r from-transparent via-brand-secondary to-transparent transition-transform duration-300 group-hover:translate-y-1"
        />
        <TriggerIcon className="h-[1.05rem] w-[1.05rem] transition-transform duration-300 group-hover:rotate-[20deg]" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[11rem]">
        {OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const active = mounted && selection === opt.value;
          return (
            <DropdownMenuItem
              key={opt.value}
              onSelect={() => setTheme(opt.value)}
              className={cn(
                "cursor-pointer gap-2",
                active && "bg-bg-elevated text-fg-default",
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{opt.label}</span>
              <span
                className={cn(
                  "font-mono text-[0.58rem] tracking-[0.18em]",
                  active ? "text-brand-secondary" : "text-fg-subtle",
                )}
              >
                {opt.hint}
              </span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
