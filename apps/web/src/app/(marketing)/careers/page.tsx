import type { Metadata } from "next";
import { ArrowUpRight } from "lucide-react";

const TITLE = "Careers — Credyx";
const DESCRIPTION =
  "Join the small team building credit intelligence on top of the world's official government registries.";

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

const ROLES = [
  {
    id: "CRX-ENG-01",
    title: "Founding Engineer — Data Adapters",
    location: "Remote (EU time zones)",
    type: "Full-time",
    body: "Own country coverage end to end: research a national business registry, reverse-engineer its API or filings format, ship a typed adapter with integration tests against the live source, and document what you found. You'll work across XBRL, ESEF, PDF pipelines, and the occasional stubborn government SOAP endpoint. Strong Python and a taste for primary sources required; prior fintech experience is not.",
  },
  {
    id: "CRX-ENG-02",
    title: "Full-Stack Engineer",
    location: "Remote (EU time zones)",
    type: "Full-time",
    body: "Build the product surface: Next.js App Router frontend, FastAPI backend, and the contracts between them. Recent work in this area includes the coverage map, the risk assessment views, and billing. You should be comfortable owning a feature from Postgres schema to Tailwind polish, and opinionated about keeping types honest across the boundary.",
  },
  {
    id: "CRX-RSK-01",
    title: "Credit Risk Analyst (part-time)",
    location: "Remote",
    type: "Part-time / contract",
    body: "Pressure-test our scoring. You'll review assessments against real filings, define industry-specific ratio benchmarks, and help decide what the model should and shouldn't be trusted to interpret. Ideal for an experienced credit underwriter who wants to shape tooling rather than use it.",
  },
];

export default function CareersPage() {
  return (
    <>
      <section className="border-b border-border-default pb-20 pt-24">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <p className="serial">Careers</p>
            <h1 className="mt-3 font-display text-display-xl tracking-tight">
              Small team. Primary sources. Real stakes.
            </h1>
            <p className="mt-6 text-lg leading-relaxed text-fg-muted">
              Credyx is a handful of people connecting the world&rsquo;s official
              company registries into one credit intelligence platform. We work
              remotely across European time zones, ship daily, and hold two
              non-negotiables: no mock data, and no arithmetic delegated to a
              language model.
            </p>
            <p className="mt-5 text-lg leading-relaxed text-fg-muted">
              If you like reading registry documentation in languages you don&rsquo;t
              speak, arguing about Altman Z-Score thresholds, or making a FastAPI
              endpoint boringly reliable, you&rsquo;ll probably like it here.
            </p>
          </div>
        </div>
      </section>

      <section className="border-b border-border-default py-20">
        <div className="container">
          <div className="mx-auto max-w-3xl">
            <h2 className="font-display text-display-lg tracking-tight">
              Open roles
            </h2>
            <div className="mt-10 space-y-6">
              {ROLES.map((role) => (
                <div
                  key={role.id}
                  className="plate rounded-xl border border-border-default bg-bg-elevated p-6 shadow-elev-1 md:p-8"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-lg font-semibold tracking-tight">
                      {role.title}
                    </h3>
                    <span className="serial">{role.id}</span>
                  </div>
                  <p className="mt-1 text-sm text-fg-subtle">
                    {role.location} &middot; {role.type}
                  </p>
                  <p className="mt-4 text-sm leading-relaxed text-fg-muted">
                    {role.body}
                  </p>
                  <a
                    href={`mailto:careers@credyx.ai?subject=${encodeURIComponent(
                      `Application: ${role.title} (${role.id})`
                    )}`}
                    className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-brand-primary underline-offset-4 hover:underline"
                  >
                    Apply via careers@credyx.ai
                    <ArrowUpRight className="h-4 w-4" aria-hidden />
                  </a>
                </div>
              ))}
            </div>

            <div className="mt-12 rounded-xl border border-border-default bg-bg-elevated p-6 text-sm leading-relaxed text-fg-muted shadow-elev-1">
              <p className="font-medium text-fg-default">
                Nothing that fits exactly?
              </p>
              <p className="mt-2">
                We read speculative applications carefully — especially from people
                who have worked with a national registry, XBRL taxonomy, or credit
                desk we haven&rsquo;t covered yet. Tell us what you&rsquo;d build at{" "}
                <a
                  href="mailto:careers@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  careers@credyx.ai
                </a>
                . No agencies, please.
              </p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
