import type { Metadata } from "next";
import Link from "next/link";
import { Rss } from "lucide-react";
import { Button } from "@/components/ui/button";

const TITLE = "Blog — Credyx";
const DESCRIPTION =
  "Field notes from the Credyx team on credit risk, registry data and AI-assisted underwriting.";

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

export default function BlogPage() {
  return (
    <section className="border-b border-border-default py-24 md:py-32">
      <div className="container">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">
            Blog
          </p>
          <h1 className="mt-3 font-display text-display-xl tracking-tight">
            Field notes, coming soon.
          </h1>
          <p className="mt-5 text-lg text-fg-muted">
            Deep dives on registry coverage, credit modelling and how we keep an LLM honest
            about a balance sheet. Subscribe and we&apos;ll send the first issue when it
            ships.
          </p>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Button asChild variant="primary" size="lg">
              <Link href="/contact">Get notified</Link>
            </Button>
            <Button asChild variant="outline" size="lg" leftIcon={<Rss className="h-4 w-4" />}>
              <Link href="/blog/rss.xml">RSS feed</Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
