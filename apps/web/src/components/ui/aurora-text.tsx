"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export interface AuroraTextProps {
  children: React.ReactNode;
  duration?: number;
  className?: string;
}

/**
 * Animated tri-stop gradient text that loops along the x-axis.
 * Inherits font-weight from its parent so it can be dropped into
 * any heading without disrupting typography.
 */
export function AuroraText({ children, duration = 8, className }: AuroraTextProps) {
  return (
    <span
      className={cn(
        "inline-block bg-clip-text text-transparent animate-gradient-x",
        className,
      )}
      style={{
        backgroundImage:
          "linear-gradient(110deg, hsl(var(--color-brand-primary)) 0%, hsl(var(--color-accent)) 50%, hsl(var(--color-brand-secondary)) 100%)",
        backgroundSize: "200% 100%",
        animationDuration: `${duration}s`,
      }}
    >
      {children}
    </span>
  );
}

export default AuroraText;
