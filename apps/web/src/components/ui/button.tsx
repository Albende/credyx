"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg-base",
  {
    variants: {
      variant: {
        primary:
          "bg-brand-primary text-brand-primary-fg hover:bg-brand-primary/90 shadow-elev-1",
        secondary:
          "bg-bg-elevated text-fg-default border border-border-default hover:bg-bg-overlay",
        outline:
          "border border-border-strong bg-transparent text-fg-default hover:bg-bg-elevated",
        ghost:
          "bg-transparent text-fg-default hover:bg-bg-elevated hover:text-fg-default",
        danger:
          "bg-danger text-fg-inverted hover:bg-danger/90 shadow-elev-1",
        destructive:
          "bg-danger text-fg-inverted hover:bg-danger/90 shadow-elev-1",
        link:
          "bg-transparent text-brand-primary underline-offset-4 hover:underline px-0 h-auto",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  fullWidth?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      asChild = false,
      loading = false,
      leftIcon,
      rightIcon,
      fullWidth = false,
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    const isDisabled = disabled || loading;
    // Radix Slot requires a single React element child. When asChild=true,
    // pass `children` straight through; ignore loading/leftIcon/rightIcon.
    if (asChild) {
      return (
        <Comp
          className={cn(buttonVariants({ variant, size }), fullWidth && "w-full", className)}
          ref={ref}
          {...props}
        >
          {children}
        </Comp>
      );
    }
    return (
      <Comp
        className={cn(buttonVariants({ variant, size }), fullWidth && "w-full", className)}
        ref={ref}
        disabled={isDisabled}
        {...props}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          leftIcon
        )}
        {children}
        {!loading && rightIcon}
      </Comp>
    );
  }
);
Button.displayName = "Button";

export { buttonVariants };
