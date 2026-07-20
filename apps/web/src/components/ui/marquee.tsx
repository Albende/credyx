"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export interface MarqueeProps {
  children: React.ReactNode;
  speed?: number;
  direction?: "left" | "right";
  pauseOnHover?: boolean;
  className?: string;
}

/**
 * Infinite horizontal scroller. Renders children twice so the
 * -50% translate loop appears seamless. Edge fades via mask-image.
 */
export function Marquee({
  children,
  speed = 40,
  direction = "left",
  pauseOnHover = true,
  className,
}: MarqueeProps) {
  const id = React.useId().replace(/:/g, "");
  const keyframe = `cl-marquee-${id}`;
  const animationDirection = direction === "right" ? "reverse" : "normal";

  return (
    <div
      className={cn(
        "group relative w-full overflow-hidden",
        className,
      )}
      style={{
        maskImage:
          "linear-gradient(to right, transparent 0%, black 8%, black 92%, transparent 100%)",
        WebkitMaskImage:
          "linear-gradient(to right, transparent 0%, black 8%, black 92%, transparent 100%)",
      }}
    >
      <style>{`
        @keyframes ${keyframe} {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
      `}</style>
      <div
        className="flex w-max items-center gap-12"
        style={{
          animation: `${keyframe} ${speed}s linear infinite`,
          animationDirection,
          animationPlayState: "running",
        }}
        onMouseEnter={(e) => {
          if (pauseOnHover) (e.currentTarget.style.animationPlayState = "paused");
        }}
        onMouseLeave={(e) => {
          if (pauseOnHover) (e.currentTarget.style.animationPlayState = "running");
        }}
      >
        <div className="flex shrink-0 items-center gap-12">{children}</div>
        <div className="flex shrink-0 items-center gap-12" aria-hidden>
          {children}
        </div>
      </div>
    </div>
  );
}

export default Marquee;
