"use client";

import * as React from "react";
import {
  animate,
  useInView,
  useMotionValue,
  useTransform,
  motion,
} from "framer-motion";
import { cn } from "@/lib/cn";

export interface AnimatedCounterProps {
  value: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  /** Optional formatter — must be a serializable inline expression in Server Components. Prefer `decimals` when called from a server component. */
  format?: (n: number) => string;
  className?: string;
}

export function AnimatedCounter({
  value,
  duration = 2,
  prefix = "",
  suffix = "",
  decimals,
  format,
  className,
}: AnimatedCounterProps) {
  const fmt = React.useMemo<(n: number) => string>(() => {
    if (format) return format;
    if (typeof decimals === "number") {
      return (n: number) =>
        n.toLocaleString(undefined, {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        });
    }
    return (n: number) => Math.round(n).toLocaleString();
  }, [format, decimals]);
  const ref = React.useRef<HTMLSpanElement | null>(null);
  const inView = useInView(ref, { once: true, amount: 0.5 });
  const mv = useMotionValue(0);
  const rounded = useTransform(mv, (latest) => fmt(latest));
  const [text, setText] = React.useState<string>(fmt(0));

  React.useEffect(() => {
    const unsub = rounded.on("change", (v) => setText(v));
    return () => unsub();
  }, [rounded]);

  React.useEffect(() => {
    if (!inView) return;
    if (value < 1) {
      mv.set(value);
      setText(fmt(value));
      return;
    }
    const controls = animate(mv, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [inView, value, duration, mv, fmt]);

  return (
    <motion.span
      ref={ref}
      className={cn("tabular-nums", className)}
      aria-label={`${prefix}${fmt(value)}${suffix}`.trim()}
    >
      {prefix}
      {text}
      {suffix}
    </motion.span>
  );
}

export default AnimatedCounter;
