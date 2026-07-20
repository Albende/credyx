import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Grain } from "@/components/ui/grain";
import { MeshGradient } from "@/components/ui/mesh-gradient";
import { Reveal } from "@/components/ui/reveal";

export function CTABanner() {
  return (
    <section className="relative isolate overflow-hidden">
      {/* Full-bleed gradient backdrop */}
      <MeshGradient intensity="vivid" />
      <Grain className="opacity-25" />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-grid bg-[length:64px_64px] opacity-[0.05] [mask-image:radial-gradient(70%_60%_at_50%_50%,black,transparent)]"
      />

      <div className="container relative py-28 md:py-36">
        <Reveal>
          <div className="mx-auto max-w-3xl text-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-border-strong/60 bg-bg-base/40 px-3 py-1 font-mono text-[0.65rem] uppercase tracking-[0.2em] text-fg-muted backdrop-blur">
              <Sparkles className="h-3 w-3 text-accent" />
              Free forever tier
            </span>

            <h2 className="mt-6 font-display text-5xl font-semibold tracking-[-0.035em] text-fg-default text-balance sm:text-6xl md:text-7xl">
              Underwrite your next deal in seconds.
            </h2>

            <p className="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-fg-muted">
              Spin up an account in under a minute and run your first live registry
              lookup today. No card, no commercial-API paywall.
            </p>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              <Button
                asChild
                size="lg"
                variant="primary"
                rightIcon={<ArrowRight className="h-4 w-4" />}
              >
                <Link href="/register">Start free trial</Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="/contact">Talk to sales</Link>
              </Button>
            </div>

            <p className="mt-8 font-mono text-[0.7rem] uppercase tracking-[0.2em] text-fg-subtle">
              No credit card · 10 free reports · Cancel any time
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
