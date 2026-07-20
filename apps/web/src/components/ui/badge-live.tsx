"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export interface BadgeLiveProps {
  label?: string;
  className?: string;
}

/**
 * Pulsing live indicator pill. A 2px success-tinted dot with a
 * radial ping behind it; small-caps label sits to the right.
 */
export function BadgeLive({ label = "LIVE", className }: BadgeLiveProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-success/30 bg-success/10 px-2.5 py-1",
        "font-mono text-[0.65rem] font-semibold uppercase tracking-[0.16em] text-success",
        className,
      )}
    >
      <span className="relative flex h-2 w-2 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-70" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
      </span>
      {label}
    </span>
  );
}

export default BadgeLive;
