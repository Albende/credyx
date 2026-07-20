import type { Variants } from "framer-motion";

/**
 * Motion primitives for the Quartz design system.
 * Keep durations modest, eases physical, choreography subtle.
 */

export const spring = { type: "spring", stiffness: 380, damping: 30 } as const;
export const springSoft = { type: "spring", stiffness: 180, damping: 28 } as const;
export const outExpo = [0.16, 1, 0.3, 1] as [number, number, number, number];

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, ease: outExpo },
  },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.5 } },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: {
      delayChildren: 0.15,
      staggerChildren: 0.08,
    },
  },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  show: {
    opacity: 1,
    scale: 1,
    transition: spring,
  },
};

export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -32 },
  show: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.6, ease: outExpo },
  },
};

export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 32 },
  show: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.6, ease: outExpo },
  },
};

export const viewportOnce = { once: true, amount: 0.25 } as const;
