"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          "flex min-h-[88px] w-full rounded-lg border border-border-default bg-bg-elevated px-3 py-2 text-sm text-fg-default placeholder:text-fg-subtle",
          "transition-colors resize-y",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus/60 focus-visible:border-border-focus",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      />
    );
  }
);
Textarea.displayName = "Textarea";
