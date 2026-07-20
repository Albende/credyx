import * as React from "react";
import { cn } from "@/lib/cn";

export interface GrainProps {
  className?: string;
}

/**
 * Server-rendered fixed-position SVG film grain overlay.
 * Sits above page surfaces, below interactive content (z-0).
 *
 * Uses `currentColor` for the grain so it inverts with the theme
 * (dark grain on light surfaces, light grain on dark). The wrapper
 * inherits `color: var(--fg-default)` from the body, which already
 * flips between themes.
 */
export function Grain({ className }: GrainProps) {
  return (
    <svg
      aria-hidden
      className={cn(
        "fixed inset-0 h-full w-full pointer-events-none text-fg-default",
        className,
      )}
      style={{
        zIndex: 0,
        opacity: 0.18,
        mixBlendMode: "soft-light",
      }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <filter id="cl-grain-filter">
        <feTurbulence
          type="fractalNoise"
          baseFrequency="0.9"
          numOctaves="2"
          stitchTiles="stitch"
        />
        <feColorMatrix
          type="matrix"
          values="0 0 0 0 0
                  0 0 0 0 0
                  0 0 0 0 0
                  0 0 0 0.6 0"
        />
        <feComposite in2="SourceGraphic" operator="in" />
      </filter>
      <rect
        width="100%"
        height="100%"
        fill="currentColor"
        filter="url(#cl-grain-filter)"
      />
    </svg>
  );
}

export default Grain;
