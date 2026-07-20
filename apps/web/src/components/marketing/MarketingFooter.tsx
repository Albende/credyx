import Link from "next/link";
import { Github, Twitter, Linkedin } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { BadgeLive } from "@/components/ui/badge-live";

type FooterLink = { href: string; label: string; external?: boolean };

const SECTIONS: { title: string; links: FooterLink[] }[] = [
  {
    title: "Product",
    links: [
      { href: "/#features", label: "Features" },
      { href: "/#how-it-works", label: "How it works" },
      { href: "/pricing", label: "Pricing" },
      { href: "/app/coverage", label: "Coverage map" },
      { href: "/app/search", label: "Live search" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: "/about", label: "About" },
      { href: "/blog", label: "Blog" },
      { href: "/contact", label: "Contact" },
      { href: "/careers", label: "Careers" },
    ],
  },
  {
    title: "Resources",
    links: [
      { href: "/api-reference", label: "API reference" },
      { href: "/app/account/api-keys", label: "API keys" },
      { href: "/changelog", label: "Changelog" },
      { href: "/app", label: "Dashboard" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/privacy", label: "Privacy" },
      { href: "/terms", label: "Terms" },
      { href: "/security", label: "Security" },
      { href: "/dpa", label: "DPA" },
    ],
  },
];

const SOCIAL = [
  { href: "https://github.com", label: "GitHub", icon: Github },
  { href: "https://twitter.com", label: "Twitter", icon: Twitter },
  { href: "https://linkedin.com", label: "LinkedIn", icon: Linkedin },
];

export function MarketingFooter() {
  return (
    <footer className="relative border-t border-border-default bg-bg-base">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-border-strong to-transparent"
      />

      <div className="container py-16">
        <div className="grid grid-cols-2 gap-10 md:grid-cols-6">
          {/* Brand column — spans 2 */}
          <div className="col-span-2">
            <Logo href="/" />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-fg-muted">
              B2B credit intelligence sourced directly from official government
              registries. Deterministic, audit-ready.
            </p>
            <div className="mt-5">
              <BadgeLive label="All systems operational" />
            </div>
            <div className="mt-6 flex items-center gap-2">
              {SOCIAL.map((s) => (
                <a
                  key={s.label}
                  href={s.href}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label={s.label}
                  className="grid h-9 w-9 place-items-center rounded-lg border border-border-default text-fg-muted transition-colors hover:border-border-strong hover:bg-bg-elevated hover:text-fg-default"
                >
                  <s.icon className="h-4 w-4" aria-hidden />
                </a>
              ))}
            </div>
          </div>

          {/* Sitemap columns */}
          {SECTIONS.map((section) => (
            <div key={section.title}>
              <h4 className="font-mono text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-fg-default">
                {section.title}
              </h4>
              <ul className="mt-4 space-y-2.5">
                {section.links.map((link) =>
                  link.external ? (
                    <li key={link.href}>
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-sm text-fg-muted transition-colors hover:text-fg-default"
                      >
                        {link.label}
                      </a>
                    </li>
                  ) : (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        className="text-sm text-fg-muted transition-colors hover:text-fg-default"
                      >
                        {link.label}
                      </Link>
                    </li>
                  )
                )}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-14 flex flex-col items-start justify-between gap-4 border-t border-border-default pt-6 text-xs text-fg-subtle md:flex-row md:items-center">
          <p>&copy; {new Date().getFullYear()} Credyx. All rights reserved.</p>
          <p className="max-w-3xl">
            Data from government registries (UK Companies House, SEC EDGAR, INSEE
            Sirene, Brønnøysund, PRH, ARES, Inforegister) plus GLEIF, OpenCorporates
            and OpenSanctions. No paid commercial APIs in the MVP.
          </p>
        </div>
      </div>
    </footer>
  );
}
