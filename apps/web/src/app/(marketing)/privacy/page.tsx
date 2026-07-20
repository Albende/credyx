import type { Metadata } from "next";
import Link from "next/link";

const TITLE = "Privacy Policy — Credyx";
const DESCRIPTION =
  "How Credyx collects, uses and protects personal data across the platform and the public registry data we process.";

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

export default function PrivacyPage() {
  return (
    <section className="border-b border-border-default pb-24 pt-24">
      <div className="container">
        <div className="mx-auto max-w-3xl">
          <p className="serial">Legal</p>
          <h1 className="mt-3 font-display text-display-lg tracking-tight">
            Privacy Policy
          </h1>
          <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-fg-subtle">
            Last updated: July 2026
          </p>

          <div className="mt-12 space-y-12 text-[0.95rem] leading-relaxed text-fg-muted">
            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                1. Who we are
              </h2>
              <p>
                Credyx (&ldquo;Credyx&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;) operates
                credyx.ai, a B2B credit intelligence platform that retrieves company data
                from official government registries and produces credit risk assessments
                for business customers. This policy explains what personal data we
                process, why, and the rights you have over it.
              </p>
              <p>
                For any privacy question or request, contact{" "}
                <a
                  href="mailto:privacy@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  privacy@credyx.ai
                </a>
                .
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                2. Data we collect from you
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  <span className="font-medium text-fg-default">Account data.</span>{" "}
                  Name, work email address, password hash, company affiliation, and
                  billing details when you register or subscribe.
                </li>
                <li>
                  <span className="font-medium text-fg-default">Usage data.</span>{" "}
                  Searches you run, companies you look up, risk analyses you request,
                  API key activity, and quota consumption. We keep this to operate
                  rate limits, billing, and your audit trail.
                </li>
                <li>
                  <span className="font-medium text-fg-default">Technical data.</span>{" "}
                  IP address, browser type, and request logs, retained for security
                  monitoring and abuse prevention.
                </li>
                <li>
                  <span className="font-medium text-fg-default">Correspondence.</span>{" "}
                  Emails you send to our sales, support, or privacy inboxes.
                </li>
              </ul>
              <p>
                We do not collect payment card numbers ourselves; card processing is
                handled by our payment provider.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                3. Public registry data
              </h2>
              <p>
                The core of the service is company information retrieved from official
                public sources: national business registers (for example UK Companies
                House, SEC EDGAR, INSEE Sirene, Brønnøysund), GLEIF, OpenCorporates,
                and OpenSanctions. This data can include personal data that appears in
                public records — typically the names, roles, and appointment dates of
                directors and officers, and names appearing on sanctions or PEP lists.
              </p>
              <p>
                We process this data as it is published at source, under our legitimate
                interest (and that of our customers) in assessing counterparty credit
                risk — a purpose compatible with the reason the data was made public.
                We do not enrich registry records with data about private individuals
                from non-public sources, and we do not invent or infer data that is not
                present in the source record.
              </p>
              <p>
                If you are a director or officer whose details appear in our cached
                registry data and you believe the source record is wrong, the
                correction must be made at the issuing registry; once corrected, a
                refresh of the record on our side will pick it up. You can request an
                immediate re-fetch or cache deletion via{" "}
                <a
                  href="mailto:privacy@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  privacy@credyx.ai
                </a>
                .
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                4. How we use data
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>Providing the service: search, lookups, financials, risk analysis.</li>
                <li>Authentication, account management, and plan enforcement.</li>
                <li>Billing and subscription management.</li>
                <li>Security monitoring, rate limiting, and abuse prevention.</li>
                <li>
                  Service communications — transactional email about your account,
                  quota, or subscription. We do not sell personal data, and we do not
                  send marketing email without consent.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                5. Legal bases (GDPR)
              </h2>
              <p>
                Where the GDPR applies, we rely on: <em>performance of a contract</em>{" "}
                for account, usage, and billing data; <em>legitimate interests</em> for
                public registry data, security logging, and product analytics;{" "}
                <em>legal obligation</em> for tax and accounting records; and{" "}
                <em>consent</em> where we ask for it explicitly.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                6. Sharing and subprocessors
              </h2>
              <p>
                We share data only with service providers who process it on our
                instructions: cloud hosting and database infrastructure, a CDN and
                TLS provider (Cloudflare), an LLM inference provider used for the
                narrative portion of risk assessments, an email delivery provider, and
                a payment processor. Each is bound by a data processing agreement.
                Financial figures sent to the LLM provider relate to companies, not to
                the analyst requesting the assessment.
              </p>
              <p>
                We may also disclose data where required by law or to protect the
                rights, safety, or property of Credyx and its users.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                7. Retention
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  Cached registry data expires after 7 days; cached filings after 30
                  days, unless refreshed earlier.
                </li>
                <li>
                  Completed risk assessments are retained for as long as your account
                  exists, so your credit decisions remain auditable.
                </li>
                <li>
                  Account data is deleted or anonymised within 30 days of account
                  closure, except where retention is legally required.
                </li>
                <li>Security logs are retained for up to 12 months.</li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                8. International transfers
              </h2>
              <p>
                Registry data originates from authorities worldwide. Where personal
                data is transferred outside the EEA or UK, we rely on adequacy
                decisions or the European Commission&rsquo;s Standard Contractual
                Clauses with our subprocessors.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                9. Your rights
              </h2>
              <p>
                Depending on your jurisdiction, you may have the right to access,
                rectify, erase, restrict, or port your personal data, and to object to
                processing based on legitimate interests. Write to{" "}
                <a
                  href="mailto:privacy@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  privacy@credyx.ai
                </a>{" "}
                and we will respond within 30 days. You also have the right to lodge a
                complaint with your supervisory authority.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                10. Security
              </h2>
              <p>
                All traffic is encrypted in transit with TLS, data is encrypted at
                rest, and administrative access is role-restricted. See our{" "}
                <Link
                  href="/security"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  security overview
                </Link>{" "}
                for detail.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                11. Changes to this policy
              </h2>
              <p>
                We will post any changes on this page and update the date above.
                Material changes affecting registered users will additionally be
                announced by email before they take effect.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
