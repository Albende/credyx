import * as React from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/cn";

export interface StatDelta {
  value: string;
  direction: "up" | "down";
}

export interface StatProps extends React.HTMLAttributes<HTMLDivElement> {
  label: React.ReactNode;
  value: React.ReactNode;
  delta?: StatDelta;
  icon?: React.ReactNode;
  hint?: React.ReactNode;
  // When true, an "up" delta is rendered as danger (used for things like default rate)
  invertDeltaTone?: boolean;
}

export const Stat = React.forwardRef<HTMLDivElement, StatProps>(
  (
    { className, label, value, delta, icon, hint, invertDeltaTone, ...props },
    ref
  ) => {
    const isPositive = delta
      ? invertDeltaTone
        ? delta.direction === "down"
        : delta.direction === "up"
      : true;
    return (
      <div
        ref={ref}
        className={cn(
          "group plate flex flex-col gap-3 rounded-xl border border-border-default bg-bg-elevated p-5 shadow-elev-1 transition-colors",
          "hover:border-border-strong",
          className
        )}
        {...props}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium uppercase tracking-wider text-fg-muted">
            {label}
          </span>
          {icon ? (
            <span className="text-fg-muted" aria-hidden>
              {icon}
            </span>
          ) : null}
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-display text-h2 font-semibold tabular-nums tracking-tight text-fg-default">
            {value}
          </span>
          {delta ? (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-medium",
                isPositive
                  ? "bg-success/15 text-success"
                  : "bg-danger/15 text-danger"
              )}
            >
              {delta.direction === "up" ? (
                <ArrowUpRight className="h-3 w-3" />
              ) : (
                <ArrowDownRight className="h-3 w-3" />
              )}
              {delta.value}
            </span>
          ) : null}
        </div>
        {hint ? <p className="text-xs text-fg-subtle">{hint}</p> : null}
      </div>
    );
  }
);
Stat.displayName = "Stat";
