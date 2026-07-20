import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium transition-colors whitespace-nowrap",
  {
    variants: {
      variant: {
        default:
          "border-border-default bg-bg-elevated text-fg-default",
        success:
          "border-success/30 bg-success/15 text-success",
        warning:
          "border-warning/30 bg-warning/15 text-warning",
        danger:
          "border-danger/30 bg-danger/15 text-danger",
        destructive:
          "border-danger/30 bg-danger/15 text-danger",
        info: "border-info/30 bg-info/15 text-info",
        brand:
          "border-brand-primary/30 bg-brand-primary/15 text-brand-primary",
        outline:
          "border-border-strong bg-transparent text-fg-default",
        secondary:
          "border-border-default bg-bg-overlay text-fg-muted",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span
      ref={ref}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
);
Badge.displayName = "Badge";

export { badgeVariants };
