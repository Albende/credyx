"use client";

import * as React from "react";
import Link from "next/link";
import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { ChevronDown, HelpCircle } from "lucide-react";
import { Reveal } from "@/components/ui/reveal";
import { cn } from "@/lib/cn";

type Faq = {
  q: string;
  a: React.ReactNode;
};

const FAQS: Faq[] = [
  {
    q: "What data sources do you use?",
    a: (
      <>
        Official government registries &mdash; UK Companies House, SEC EDGAR, INSEE
        Sirene, KvK, Brønnøysund, PRH, ARES, Inforegister and dozens more &mdash; plus
        GLEIF, OpenCorporates and OpenSanctions. The full list of 112 countries is at{" "}
        <Link
          href="/app/coverage"
          className="font-medium text-brand-primary underline-offset-4 hover:underline"
        >
          /coverage
        </Link>
        .
      </>
    ),
  },
  {
    q: "Is the data real-time?",
    a: (
      <>
        Registries are queried live the first time you look up a company. We cache
        company records for 7 days and filed financials for 30 days; pass{" "}
        <code className="rounded bg-bg-overlay px-1 py-0.5 font-mono text-xs">
          ?force_refresh=true
        </code>{" "}
        on any endpoint to bypass the cache.
      </>
    ),
  },
  {
    q: "How is risk scored?",
    a: (
      <>
        Deterministic financial ratios &mdash; current, quick, debt-to-equity, ROE, ROA,
        Altman-Z &mdash; are computed in pure Python before any LLM call. Those values
        and the registry context are passed to Gemini, which returns a 0&ndash;100
        score, an APPROVE / REVIEW / REJECT recommendation and a recommended credit
        limit in EUR. OpenSanctions matches above the confidence threshold force an
        automatic REJECT before the model runs.
      </>
    ),
  },
  {
    q: "What plans do you offer?",
    a: (
      <>
        Free, Starter, Pro and Enterprise. The Free tier includes 10 reports per month;
        Pro adds API access and bulk processing. See full pricing at{" "}
        <Link
          href="/pricing"
          className="font-medium text-brand-primary underline-offset-4 hover:underline"
        >
          /pricing
        </Link>
        .
      </>
    ),
  },
  {
    q: "Can I use this via API?",
    a: (
      <>
        Yes, on Pro and Enterprise plans. Generate and rotate API keys at{" "}
        <Link
          href="/app/account/api-keys"
          className="font-medium text-brand-primary underline-offset-4 hover:underline"
        >
          /app/account/api-keys
        </Link>{" "}
        and read the reference at the public OpenAPI doc.
      </>
    ),
  },
  {
    q: "Where are you compliant?",
    a: (
      <>
        No personally identifiable data is stored by default &mdash; only company
        records and your search queries. GDPR-compatible processing, encrypted-at-rest
        storage and SOC2-style operational controls are on the roadmap. Talk to us if
        you need a DPA or vendor assessment.
      </>
    ),
  },
];

export function FAQAccordion() {
  return (
    <section className="relative border-b border-border-default py-24 md:py-32">
      <div className="container">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-[0.7rem] font-semibold uppercase tracking-[0.22em] text-accent">
              FAQ
            </p>
            <h2 className="mt-4 font-display text-5xl font-semibold tracking-[-0.03em] text-fg-default text-balance sm:text-6xl">
              Questions, answered.
            </h2>
          </div>
        </Reveal>

        <Reveal>
          <div className="mx-auto mt-14 max-w-3xl rounded-2xl border border-border-default/80 bg-bg-elevated/60 p-2 shadow-depth-1 backdrop-blur">
            <AccordionPrimitive.Root type="single" collapsible className="w-full">
              {FAQS.map((f, i) => (
                <AccordionPrimitive.Item
                  key={f.q}
                  value={`faq-${i}`}
                  className={cn(
                    "group rounded-xl px-4 transition-colors data-[state=open]:bg-bg-base/40",
                    i !== FAQS.length - 1 && "border-b border-border-default/60"
                  )}
                >
                  <AccordionPrimitive.Header className="flex">
                    <AccordionPrimitive.Trigger
                      className={cn(
                        "flex flex-1 items-center justify-between gap-4 py-5 text-left text-base font-medium text-fg-default transition-all",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus/60 rounded-md",
                        "[&[data-state=open]>svg]:rotate-180 [&[data-state=open]>svg]:text-brand-primary"
                      )}
                    >
                      <span className="flex items-center gap-3">
                        <HelpCircle className="h-4 w-4 text-fg-subtle transition-colors group-data-[state=open]:text-brand-primary" />
                        {f.q}
                      </span>
                      <ChevronDown className="h-4 w-4 shrink-0 text-fg-muted transition-transform duration-300 ease-out" />
                    </AccordionPrimitive.Trigger>
                  </AccordionPrimitive.Header>
                  <AccordionPrimitive.Content
                    className={cn(
                      "overflow-hidden text-sm leading-relaxed text-fg-muted",
                      "data-[state=closed]:animate-[acc-up_220ms_cubic-bezier(0.16,1,0.3,1)]",
                      "data-[state=open]:animate-[acc-down_280ms_cubic-bezier(0.16,1,0.3,1)]"
                    )}
                  >
                    <div className="pb-5 pl-7 pr-2 pt-0">{f.a}</div>
                  </AccordionPrimitive.Content>
                </AccordionPrimitive.Item>
              ))}
            </AccordionPrimitive.Root>
          </div>
        </Reveal>
      </div>

      {/* Smooth height keyframes for Radix Accordion */}
      <style jsx global>{`
        @keyframes acc-down {
          from {
            height: 0;
            opacity: 0;
          }
          to {
            height: var(--radix-accordion-content-height);
            opacity: 1;
          }
        }
        @keyframes acc-up {
          from {
            height: var(--radix-accordion-content-height);
            opacity: 1;
          }
          to {
            height: 0;
            opacity: 0;
          }
        }
      `}</style>
    </section>
  );
}
