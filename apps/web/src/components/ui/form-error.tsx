import * as React from "react";
import { cn } from "@/lib/cn";

export interface FormErrorProps extends React.HTMLAttributes<HTMLParagraphElement> {
  message?: string | null;
}

export const FormError = React.forwardRef<HTMLParagraphElement, FormErrorProps>(
  ({ className, message, children, ...props }, ref) => {
    const text = message ?? children;
    if (!text) return null;
    return (
      <p
        ref={ref}
        role="alert"
        className={cn("text-small text-danger", className)}
        {...props}
      >
        {text}
      </p>
    );
  }
);
FormError.displayName = "FormError";
