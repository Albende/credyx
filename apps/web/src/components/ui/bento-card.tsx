"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export interface BentoCardProps {
  className?: string;
  children: React.ReactNode;
  span?: string;
  title?: React.ReactNode;
  eyebrow?: string;
  icon?: React.ReactNode;
}

/**
 * Bento-grid card with mouse-tracked radial spotlight on hover.
 * Layered surface: hairline border + soft fill + inner highlight
 * + cursor-following indigo glow that fades when the cursor leaves.
 */
export function BentoCard({
  className,
  children,
  span,
  title,
  eyebrow,
  icon,
}: BentoCardProps) {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = React.useState<{ x: number; y: number }>({ x: -200, y: -200 });
  const [opacity, setOpacity] = React.useState(0);

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      className={cn(
        "group relative overflow-hidden rounded-2xl border border-border-default bg-bg-elevated p-6",
        "transition-colors duration-300 hover:border-border-strong",
        "shadow-depth-1 hover:shadow-depth-2",
        span,
        className,
      )}
    >
      {/* Cursor spotlight */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 transition-opacity duration-300"
        style={{
          opacity,
          background: `radial-gradient(360px circle at ${pos.x}px ${pos.y}px, hsl(var(--color-brand-primary) / 0.14), transparent 70%)`,
        }}
      />
      {/* Inner top-edge highlight — inverts with theme so it shows up
          on both light (subtle dark hairline) and dark (subtle light) */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-fg-default/10 to-transparent"
      />

      {(eyebrow || icon || title) && (
        <header className="relative mb-4 flex items-start gap-3">
          {icon && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border-default bg-bg-overlay text-brand-primary">
              {icon}
            </span>
          )}
          <div className="min-w-0">
            {eyebrow && (
              <div className="font-mono text-[0.68rem] font-medium uppercase tracking-[0.14em] text-fg-subtle">
                {eyebrow}
              </div>
            )}
            {title && (
              <div className="mt-0.5 font-display text-lg font-semibold tracking-tight text-fg-default">
                {title}
              </div>
            )}
          </div>
        </header>
      )}

      <div className="relative">{children}</div>
    </div>
  );
}

export default BentoCard;
