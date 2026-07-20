import type { Metadata } from "next";

const TITLE = "Changelog — Credyx";
const DESCRIPTION =
  "Product updates from the Credyx team: new country coverage, platform features, and design changes.";

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

const ENTRIES = [
  {
    date: "July 2026",
    tag: "Design",
    title: "The Bureau design system — and Credyx",
    points: [
      "CreditLens is now Credyx. New name, new domain (credyx.ai), same non-negotiables.",
      "Shipped “Bureau”, a full design system drawn from security printing: engraved guilloché line-work, ledger rules, registration ticks, and stamped verdicts.",
      "Two themes: Bond (ivory paper and green ink) and Vault (green-black with jade phosphor), with an animated shade-pull theme switch.",
      "Every marketing, app, and admin surface re-cut on the new tokens — no page left on the old palette.",
    ],
  },
  {
    date: "July 2026",
    tag: "Coverage",
    title: "Global coverage expansion: 100+ country adapters",
    points: [
      "Adapter registry grown from 8 live countries to 100+ jurisdictions, backed by official registries plus GLEIF, OpenCorporates, and OpenSanctions.",
      "New XBRL and ESEF parsers for structured financials, and a PDF text-extraction pipeline for filing formats that never heard of structured data.",
      "Playwright browser pool with out-of-band ingestion queue for registries that only speak HTML — scraping never blocks a live request.",
      "Sanctions and PEP screening wired into the risk pipeline: hits surface as automatic red flags before the model runs.",
    ],
  },
  {
    date: "July 2026",
    tag: "Platform",
    title: "Accounts, plans, and billing",
    points: [
      "Full authentication: registration, email verification, password reset, and revocable bearer tokens.",
      "Subscription plans with per-plan quotas — searches per day, lookups per day, financial pulls and risk analyses per month — enforced server-side on every endpoint.",
      "API keys manageable from the dashboard for programmatic access to the full REST surface.",
      "Admin console for user management, plan configuration, metrics, and the audit log.",
    ],
  },
  {
    date: "May 2026",
    tag: "Launch",
    title: "Initial MVP",
    points: [
      "First release: live search, company lookup, and filed financials for 8 countries — UK, US, France, Netherlands, Czechia, Estonia, Norway, Finland.",
      "Deterministic risk engine: current ratio, quick ratio, debt-to-equity, ROE, ROA, and Altman Z-Score computed in code; the LLM interprets, it never does arithmetic.",
      "Structured RiskAssessment output — score 0–100, APPROVE/REVIEW/REJECT, recommended credit limit in EUR — persisted permanently for audit.",
      "Postgres caching with honest freshness: 7-day TTL on registry data, 30 days on filings, force_refresh everywhere.",
    ],
  },
];

export default function ChangelogPage() {
  return (
    <section className="border-b border-border-default pb-24 pt-24">
      <div className="container">
        <div className="mx-auto max-w-3xl">
          <p className="serial">Resources</p>
          <h1 className="mt-3 font-display text-display-xl tracking-tight">
            Changelog
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-fg-muted">
            What shipped, when, in plain language. Entries cover product,
            coverage, and design changes that affect what you can do with Credyx.
          </p>

          <div className="mt-14 space-y-10">
            {ENTRIES.map((entry) => (
              <article
                key={entry.title}
                className="relative border-l border-border-strong pl-6 md:pl-8"
              >
                <span
                  aria-hidden
                  className="absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border border-border-strong bg-bg-base"
                />
                <div className="flex flex-wrap items-center gap-3">
                  <p className="serial">{entry.date}</p>
                  <span className="badge">{entry.tag}</span>
                </div>
                <h2 className="mt-2 font-display text-2xl tracking-tight">
                  {entry.title}
                </h2>
                <ul className="mt-4 list-disc space-y-2 pl-5 text-[0.95rem] leading-relaxed text-fg-muted">
                  {entry.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
