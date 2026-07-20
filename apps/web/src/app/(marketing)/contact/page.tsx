import type { Metadata } from "next";
import { Mail, MessageSquare, Building2 } from "lucide-react";

const TITLE = "Contact — Credyx";
const DESCRIPTION =
  "Get in touch with Credyx — sales, support, and partnership inquiries welcome.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    images: ["/og/og-home.png"],
  },
};

const CHANNELS = [
  {
    icon: Mail,
    title: "Sales",
    body: "Enterprise plans, volume pricing, custom data sources.",
    contact: "sales@credyx.ai",
    href: "mailto:sales@credyx.ai",
  },
  {
    icon: MessageSquare,
    title: "Support",
    body: "Account questions, API issues, and bug reports.",
    contact: "support@credyx.ai",
    href: "mailto:support@credyx.ai",
  },
  {
    icon: Building2,
    title: "Partnerships",
    body: "Reseller, integration, and data partnership inquiries.",
    contact: "partners@credyx.ai",
    href: "mailto:partners@credyx.ai",
  },
];

export default function ContactPage() {
  return (
    <section className="border-b border-border-default py-24 md:py-32">
      <div className="container">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
            Contact
          </p>
          <h1 className="mt-3 font-display text-display-xl tracking-tight">
            We read everything.
          </h1>
          <p className="mt-5 text-lg text-fg-muted">
            Pick the right inbox below and we&apos;ll get back to you within one business
            day.
          </p>
        </div>

        <div className="mx-auto mt-16 grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-3">
          {CHANNELS.map((c) => (
            <a
              key={c.title}
              href={c.href}
              className="group rounded-xl border border-border-default bg-bg-elevated p-6 shadow-elev-1 transition-colors hover:border-border-strong"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-border-default bg-bg-base transition-colors group-hover:border-brand-primary/40 group-hover:bg-brand-primary/10">
                <c.icon
                  className="h-5 w-5 text-accent transition-colors group-hover:text-brand-primary"
                  aria-hidden
                />
              </div>
              <h3 className="mt-5 text-base font-semibold tracking-tight">{c.title}</h3>
              <p className="mt-2 text-sm text-fg-muted">{c.body}</p>
              <p className="mt-4 text-sm font-medium text-brand-primary group-hover:underline">
                {c.contact}
              </p>
            </a>
          ))}
        </div>

        <div className="mx-auto mt-16 max-w-3xl rounded-xl border border-border-default bg-bg-elevated p-8 text-sm text-fg-muted shadow-elev-1">
          <p className="font-medium text-fg-default">Press &amp; analyst inquiries</p>
          <p className="mt-2">
            For interviews, briefings or quotes, write to{" "}
            <a
              href="mailto:press@credyx.ai"
              className="font-medium text-brand-primary underline-offset-4 hover:underline"
            >
              press@credyx.ai
            </a>
            . Please include your outlet, deadline and angle.
          </p>
        </div>
      </div>
    </section>
  );
}
