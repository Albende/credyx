import * as React from "react";
import { cn } from "@/lib/cn";

export interface EmptyStateProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
}

export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ className, icon, title, description, action, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border-strong bg-bg-elevated/40 px-6 py-12 text-center",
        className
      )}
      {...props}
    >
      {icon ? (
        <div
          className="flex h-12 w-12 items-center justify-center rounded-full bg-bg-overlay text-fg-muted"
          aria-hidden
        >
          {icon}
        </div>
      ) : null}
      <div className="space-y-1">
        <h3 className="text-h4 font-semibold text-fg-default">{title}</h3>
        {description ? (
          <p className="mx-auto max-w-md text-sm text-fg-muted">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
);
EmptyState.displayName = "EmptyState";
