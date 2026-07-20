import type { ReactNode } from "react";
import Link from "next/link";
import { Search, Gauge, ShieldCheck } from "lucide-react";
import { Toaster } from "@/components/ui/toaster";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Logo } from "@/components/ui/logo";
import { MeshGradient } from "@/components/ui/mesh-gradient";
import { Grain } from "@/components/ui/grain";
import { BadgeLive } from "@/components/ui/badge-live";
import { AuroraText } from "@/components/ui/aurora-text";

const features = [
  {
    icon: Search,
    title: "Registry-grade sourcing",
    body: "Live filings from 100+ official government registries — never synthesized.",
  },
  {
    icon: Gauge,
    title: "Deterministic ratios",
    body: "Altman-Z, liquidity, leverage — computed locally before the model ever sees them.",
  },
  {
    icon: ShieldCheck,
    title: "Audit-ready trails",
    body: "Every assessment is persisted with sources, prompts, and timestamps.",
  },
];

export default function AuthLayout({ children }: { children: ReactNode }) {
  const year = new Date().getFullYear();

  return (
    <div className="relative min-h-screen bg-bg-base">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-5">
        {/* LEFT — editorial backdrop (60% on lg+) */}
        <aside className="relative hidden lg:col-span-3 lg:flex lg:flex-col lg:justify-between lg:overflow-hidden lg:px-12 lg:py-10 xl:px-16">
          <MeshGradient intensity="vivid" />
          <Grain className="absolute inset-0 h-full w-full opacity-[0.18]" />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-1/2 [mask-image:linear-gradient(to_bottom,black,transparent)]"
          >
            <div className="texture-guilloche absolute inset-0 text-brand-primary/[0.08]" />
          </div>

          {/* Brand + live badge */}
          <div className="relative z-10 flex items-center justify-between">
            <Logo href="/" />
            <BadgeLive label="Trusted by 500+ teams" />
          </div>

          {/* Editorial headline + bullets */}
          <div className="relative z-10 max-w-2xl space-y-10">
            <div className="space-y-6">
              <h1 className="font-display text-display-lg leading-[1.02] tracking-tight text-fg-default">
                Credit intelligence at{" "}
                <AuroraText className="font-display">registry-speed.</AuroraText>
              </h1>
              <p className="max-w-xl text-base leading-relaxed text-fg-muted">
                Credyx pulls official filings, computes deterministic
                ratios, and returns an auditable risk score — in seconds,
                across jurisdictions.
              </p>
            </div>

            <ul className="space-y-5">
              {features.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex items-start gap-4">
                  <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border-default/70 bg-bg-elevated/60 backdrop-blur-sm">
                    <Icon className="h-4 w-4 text-brand-primary" aria-hidden />
                  </span>
                  <div className="space-y-0.5">
                    <p className="text-sm font-semibold text-fg-default">
                      {title}
                    </p>
                    <p className="text-sm text-fg-muted">{body}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* Testimonial */}
          <figure className="relative z-10 max-w-xl rounded-2xl border border-border-default/70 bg-bg-elevated/40 p-6 backdrop-blur-md">
            <svg
              aria-hidden
              className="mb-3 h-5 w-5 text-brand-primary/70"
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path d="M7.17 6C4.85 6 3 7.85 3 10.17v2.66C3 15.16 4.85 17 7.17 17h.33v-3.5H6c-.55 0-1-.45-1-1v-2.33C5 9.07 6.07 8 7.17 8H8V6h-.83zm9 0c-2.32 0-4.17 1.85-4.17 4.17v2.66c0 2.33 1.85 4.17 4.17 4.17h.33v-3.5H15c-.55 0-1-.45-1-1v-2.33C14 9.07 15.07 8 16.17 8H17V6h-.83z" />
            </svg>
            <blockquote className="text-sm leading-relaxed text-fg-default">
              &ldquo;We replaced two vendors and a spreadsheet workflow with
              Credyx in a single sprint. The fact that every ratio is
              computed in-process — not hallucinated — is what closed the
              deal for our risk committee.&rdquo;
            </blockquote>
            <figcaption className="mt-4 flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full border border-border-default bg-bg-inset text-xs font-semibold text-fg-default">
                MK
              </span>
              <div className="text-xs leading-tight">
                <p className="font-medium text-fg-default">Maja Krüger</p>
                <p className="text-fg-muted">Head of Credit, Nordwind Trade</p>
              </div>
            </figcaption>
          </figure>
        </aside>

        {/* RIGHT — form surface (40% on lg+) */}
        <section className="relative col-span-1 flex min-h-screen flex-col bg-bg-elevated lg:col-span-2">
          <div className="absolute right-4 top-4 lg:right-6 lg:top-6">
            <ThemeToggle />
          </div>

          {/* Mobile-only brand mark (left column hidden < lg) */}
          <div className="px-6 pt-8 lg:hidden">
            <Logo href="/" />
          </div>

          <div className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10 lg:px-12">
            <div className="w-full max-w-md">
              {/* Brand mark above form on lg+ */}
              <div className="mb-10 hidden lg:flex">
                <Logo href="/" />
              </div>
              {children}
            </div>
          </div>

          <footer className="px-6 pb-6 text-center text-xs text-fg-subtle lg:px-12 lg:text-left">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p>&copy; {year} Credyx. All rights reserved.</p>
              <nav className="flex items-center justify-center gap-4">
                <Link href="/terms" className="hover:text-fg-default">
                  Terms
                </Link>
                <Link href="/privacy" className="hover:text-fg-default">
                  Privacy
                </Link>
                <Link href="/contact" className="hover:text-fg-default">
                  Contact
                </Link>
              </nav>
            </div>
          </footer>
        </section>
      </div>

      <Toaster />
    </div>
  );
}
