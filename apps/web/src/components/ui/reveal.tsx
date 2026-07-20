"use client";

import * as React from "react";
import { motion, type MotionProps } from "framer-motion";
import { fadeUp, staggerContainer, viewportOnce } from "@/lib/motion";

type RevealTag = "div" | "section" | "article" | "header" | "footer" | "ul" | "li" | "span";

export interface RevealProps {
  as?: RevealTag;
  delay?: number;
  stagger?: boolean;
  className?: string;
  children: React.ReactNode;
}

/**
 * Scroll-triggered fade-up wrapper. When stagger=true, children
 * inheriting fadeUp variants animate in sequence.
 */
export function Reveal({
  as = "div",
  delay = 0,
  stagger = false,
  className,
  children,
}: RevealProps) {
  const MotionTag = motion[as] as React.ComponentType<MotionProps & { className?: string }>;

  const variants = stagger ? staggerContainer : fadeUp;
  const transition = delay > 0 && !stagger ? { delay } : undefined;

  return (
    <MotionTag
      className={className}
      variants={variants}
      initial="hidden"
      whileInView="show"
      viewport={viewportOnce}
      transition={transition}
    >
      {children}
    </MotionTag>
  );
}

export default Reveal;
