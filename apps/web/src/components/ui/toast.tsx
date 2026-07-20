"use client";

import * as React from "react";
import { Toaster as SonnerToaster, toast } from "sonner";

export type ToasterProps = React.ComponentProps<typeof SonnerToaster>;

export const Toaster = ({ ...props }: ToasterProps) => (
  <SonnerToaster
    theme="dark"
    position="bottom-right"
    toastOptions={{
      classNames: {
        toast:
          "group toast bg-bg-overlay text-fg-default border border-border-default shadow-elev-2 rounded-lg",
        title: "text-sm font-semibold text-fg-default",
        description: "text-sm text-fg-muted",
        actionButton:
          "bg-brand-primary text-brand-primary-fg rounded-md px-2 py-1 text-xs",
        cancelButton:
          "bg-bg-elevated text-fg-muted rounded-md px-2 py-1 text-xs",
        error: "border-danger/40",
        success: "border-success/40",
        warning: "border-warning/40",
        info: "border-info/40",
      },
    }}
    {...props}
  />
);

export { toast };
