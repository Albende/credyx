"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Quote } from "lucide-react";
import { Marquee } from "@/components/ui/marquee";
import { Reveal } from "@/components/ui/reveal";

type Testimonial = {
  quote: string;
  initials: string;
  role: string;
  company: string;
  tint: "indigo" | "amber" | "teal" | "violet" | "rose";
};

const TESTIMONIALS: Testimonial[] = [
  {
    quote:
      "We used to wait days for a third-party report on a Czech supplier. Credyx pulls the ARES filing in seconds and the ratios are computed exactly like our analysts do them.",
    initials: "LS",
    role: "Head of Trade Credit",
    company: "Nordic logistics group",
    tint: "indigo",
  },
  {
    quote:
      "The fact that the LLM never invents a number is what sold us. Every figure on the report traces back to a registry document we can pull on demand.",
    initials: "MW",
    role: "Director of Credit Risk",
    company: "Mid-cap asset manager",
    tint: "amber",
  },
  {
    quote:
      "OpenSanctions integration caught two exposures our existing screener missed. The auto-REJECT before the model runs is exactly the workflow we wanted.",
    initials: "AR",
    role: "Compliance Lead",
    company: "Commodity trading desk",
    tint: "teal",
  },
  {
    quote:
      "GLEIF fallback on long-tail jurisdictions is the killer feature. We onboarded a Mauritian counterparty last week without picking up the phone once.",
    initials: "DO",
    role: "AR Manager",
    company: "Cross-border distributor",
    tint: "violet",
  },
  {
    quote:
      "I've replaced three tools with Credyx. Registry data, sanctions, financial ratios — all sourced, all auditable. My team finally trusts the output.",
    initials: "EK",
    role: "VP Risk",
    company: "Mid-cap manufacturer",
    tint: "rose",
  },
];

const TINTS: Record<Testimonial["tint"], string> = {
  indigo: "from-brand-primary/25 to-transparent text-brand-primary",
  amber: "from-brand-secondary/25 to-transparent text-brand-secondary",
  teal: "from-accent/25 to-transparent text-accent",
  violet: "from-info/25 to-transparent text-info",
  rose: "from-danger/20 to-transparent text-danger",
};

export function TestimonialsCarousel() {
  return (
    <section className="relative border-b border-border-default py-24 md:py-32">
      <div className="container">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-accent">
              What teams say
            </p>
            <h2 className="mt-4 font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default text-balance sm:text-6xl">
              Built with credit teams, for credit teams.
            </h2>
          </div>
        </Reveal>
      </div>

      <div className="mt-16">
        <Marquee speed={70} pauseOnHover>
          <div className="flex items-stretch gap-6 px-6">
            {TESTIMONIALS.map((t, i) => (
              <TestimonialCard key={t.initials + i} t={t} index={i} />
            ))}
          </div>
        </Marquee>
      </div>
    </section>
  );
}

function TestimonialCard({ t, index }: { t: Testimonial; index: number }) {
  const tintClass = TINTS[t.tint];
  return (
    <motion.figure
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.55, delay: Math.min(index * 0.05, 0.3), ease: [0.16, 1, 0.3, 1] }}
      className="relative flex w-[360px] shrink-0 flex-col rounded-2xl border border-border-default/80 bg-bg-elevated/70 p-6 shadow-depth-1 backdrop-blur md:w-[400px]"
    >
      <div
        aria-hidden
        className={`pointer-events-none absolute inset-x-0 top-0 h-24 rounded-t-2xl bg-gradient-to-b ${tintClass} opacity-50`}
      />
      <Quote className={`relative h-5 w-5 ${tintClass.split(" ").pop()}`} aria-hidden />
      <blockquote className="relative mt-4 text-[15px] leading-relaxed text-fg-default">
        &ldquo;{t.quote}&rdquo;
      </blockquote>
      <figcaption className="relative mt-6 flex items-center gap-3 border-t border-border-default/70 pt-4">
        <div
          className={`grid h-10 w-10 place-items-center rounded-full bg-bg-base text-sm font-semibold ${tintClass.split(" ").pop()}`}
        >
          {t.initials}
        </div>
        <div className="text-sm">
          <div className="font-medium text-fg-default">{t.role}</div>
          <div className="text-fg-muted">{t.company}</div>
        </div>
      </figcaption>
    </motion.figure>
  );
}
