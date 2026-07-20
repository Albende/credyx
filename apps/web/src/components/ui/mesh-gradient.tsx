"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

type Intensity = "subtle" | "normal" | "vivid";

const opacityMap: Record<Intensity, { a: number; b: number; c: number; overlay: number }> = {
  subtle: { a: 0.18, b: 0.14, c: 0.12, overlay: 0.55 },
  normal: { a: 0.32, b: 0.26, c: 0.22, overlay: 0.42 },
  vivid: { a: 0.5, b: 0.42, c: 0.36, overlay: 0.32 },
};

export interface MeshGradientProps {
  className?: string;
  intensity?: Intensity;
}

export function MeshGradient({ className, intensity = "normal" }: MeshGradientProps) {
  const { a, b, c, overlay } = opacityMap[intensity];

  return (
    <div
      aria-hidden
      className={cn("absolute inset-0 overflow-hidden pointer-events-none -z-10", className)}
    >
      {/* Animated radial blobs */}
      <div
        className="absolute -inset-[20%] animate-aurora will-change-transform"
        style={{
          backgroundImage: `
            radial-gradient(40% 35% at 18% 22%, hsl(var(--color-brand-primary) / ${a}) 0%, transparent 70%),
            radial-gradient(38% 32% at 82% 28%, hsl(var(--color-brand-secondary) / ${b}) 0%, transparent 70%),
            radial-gradient(45% 40% at 50% 88%, hsl(var(--color-accent) / ${c}) 0%, transparent 70%)
          `,
          filter: "blur(40px) saturate(120%)",
        }}
      />
      {/* Counter-rotating second layer for organic motion */}
      <div
        className="absolute -inset-[30%] animate-aurora opacity-60 will-change-transform"
        style={{
          animationDirection: "reverse",
          animationDuration: "22s",
          backgroundImage: `
            radial-gradient(30% 28% at 70% 60%, hsl(var(--color-brand-primary) / ${a * 0.7}) 0%, transparent 70%),
            radial-gradient(34% 30% at 28% 72%, hsl(var(--color-accent) / ${c * 0.8}) 0%, transparent 70%)
          `,
          filter: "blur(60px)",
        }}
      />
      {/* Dark veil for text legibility */}
      <div
        className="absolute inset-0"
        style={{
          background: `linear-gradient(to bottom, hsl(var(--color-bg-base) / ${overlay * 0.6}) 0%, hsl(var(--color-bg-base) / ${overlay}) 100%)`,
        }}
      />
    </div>
  );
}

export default MeshGradient;
