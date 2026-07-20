"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", invalid, ...props }, ref) => {
    return (
      <input
        ref={ref}
        type={type}
        aria-invalid={invalid || undefined}
        className={cn(
          "flex h-10 w-full rounded-lg border border-border-default bg-bg-elevated px-3 py-2 text-sm text-fg-default placeholder:text-fg-subtle",
          "transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus/60 focus-visible:border-border-focus",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "file:border-0 file:bg-transparent file:text-sm file:font-medium",
          invalid && "border-danger focus-visible:ring-danger/60 focus-visible:border-danger",
          className
        )}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export interface InputGroupProps
  extends React.HTMLAttributes<HTMLDivElement> {
  leftAdornment?: React.ReactNode;
  rightAdornment?: React.ReactNode;
}

export const InputGroup = React.forwardRef<HTMLDivElement, InputGroupProps>(
  ({ className, leftAdornment, rightAdornment, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn("relative flex w-full items-center", className)}
        {...props}
      >
        {leftAdornment ? (
          <div className="pointer-events-none absolute left-3 flex h-full items-center text-fg-muted">
            {leftAdornment}
          </div>
        ) : null}
        <div
          className={cn(
            "w-full",
            leftAdornment && "[&_input]:pl-9",
            rightAdornment && "[&_input]:pr-9"
          )}
        >
          {children}
        </div>
        {rightAdornment ? (
          <div className="absolute right-3 flex h-full items-center text-fg-muted">
            {rightAdornment}
          </div>
        ) : null}
      </div>
    );
  }
);
InputGroup.displayName = "InputGroup";

// Re-exports for shadcn-style imports where Label/Textarea come from "input"
export { Label } from "./label";
export { Textarea } from "./textarea";
