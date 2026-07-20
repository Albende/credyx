import type { Metadata } from "next";
import Link from "next/link";

const TITLE = "Terms of Service — Credyx";
const DESCRIPTION =
  "The terms that govern use of the Credyx platform, API and credit risk assessments.";

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

export default function TermsPage() {
  return (
    <section className="border-b border-border-default pb-24 pt-24">
      <div className="container">
        <div className="mx-auto max-w-3xl">
          <p className="serial">Legal</p>
          <h1 className="mt-3 font-display text-display-lg tracking-tight">
            Terms of Service
          </h1>
          <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-fg-subtle">
            Last updated: July 2026
          </p>

          <div className="mt-12 space-y-12 text-[0.95rem] leading-relaxed text-fg-muted">
            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                1. Agreement
              </h2>
              <p>
                These Terms of Service (the &ldquo;Terms&rdquo;) govern access to and
                use of the Credyx platform, website, and API (the
                &ldquo;Service&rdquo;) provided by Credyx (&ldquo;Credyx&rdquo;,
                &ldquo;we&rdquo;, &ldquo;us&rdquo;). By creating an account or using
                the Service you agree to these Terms on behalf of yourself and, where
                applicable, the organisation you represent. The Service is offered to
                businesses; it is not intended for consumers.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                2. The Service
              </h2>
              <p>
                Credyx retrieves company registry data and filed financial statements
                from official government sources and free public aggregators, computes
                financial ratios deterministically, and produces structured credit risk
                assessments. Coverage, capabilities, and rate limits vary by country
                and by subscription plan; the current coverage is shown on the{" "}
                <Link
                  href="/app/coverage"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  coverage map
                </Link>
                . Where a source cannot return real data, the Service returns an
                explicit &ldquo;not implemented&rdquo; error rather than substitute
                data.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                3. Accounts and API keys
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  You must provide accurate registration information and keep your
                  credentials confidential. You are responsible for all activity under
                  your account and API keys.
                </li>
                <li>
                  API keys are issued per account and may not be shared outside your
                  organisation or embedded in publicly accessible client-side code.
                </li>
                <li>
                  Notify us promptly at{" "}
                  <a
                    href="mailto:support@credyx.ai"
                    className="font-medium text-brand-primary underline-offset-4 hover:underline"
                  >
                    support@credyx.ai
                  </a>{" "}
                  if you suspect unauthorised use of your account.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                4. Acceptable use
              </h2>
              <p>You agree not to:</p>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  circumvent rate limits, quotas, or plan restrictions, or probe or
                  disrupt the Service&rsquo;s infrastructure;
                </li>
                <li>
                  resell, sublicense, or systematically redistribute Service output as
                  a standalone dataset or competing service;
                </li>
                <li>
                  use the Service to make decisions about consumers&rsquo; access to
                  credit, employment, housing, or insurance — the Service assesses
                  companies, not individuals;
                </li>
                <li>
                  use the Service in violation of applicable law, including sanctions
                  and export-control regulations;
                </li>
                <li>
                  misrepresent Service output as originating from a government
                  registry when it has been transformed or scored by Credyx.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                5. Data accuracy and no financial advice
              </h2>
              <p>
                Registry data is reproduced from official sources as published and may
                itself contain errors, be incomplete, or be out of date. Risk scores,
                recommendations, and suggested credit limits are decision-support
                outputs generated from that data; they are{" "}
                <span className="font-medium text-fg-default">
                  not financial, legal, or investment advice
                </span>
                , and they are not a guarantee of any counterparty&rsquo;s
                creditworthiness or solvency. You remain solely responsible for your
                credit decisions and for complying with any regulatory requirements
                that apply to them.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                6. Fees and billing
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  Paid plans are billed in advance on a recurring basis at the prices
                  shown on the{" "}
                  <Link
                    href="/pricing"
                    className="font-medium text-brand-primary underline-offset-4 hover:underline"
                  >
                    pricing page
                  </Link>{" "}
                  at the time of purchase. Prices exclude VAT and similar taxes.
                </li>
                <li>
                  Usage quotas (searches, lookups, risk analyses) reset per billing
                  period and do not roll over.
                </li>
                <li>
                  You may cancel at any time; cancellation takes effect at the end of
                  the current billing period. Fees already paid are non-refundable
                  except where required by law.
                </li>
                <li>
                  We may change prices with at least 30 days&rsquo; notice, effective
                  from your next billing period.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                7. Intellectual property
              </h2>
              <p>
                Credyx retains all rights in the Service, its software, and its
                branding. You retain all rights in the data you submit. Registry data
                remains subject to the terms of the issuing authority. We grant you a
                non-exclusive, non-transferable licence to use Service output within
                your organisation for internal credit-risk purposes for the duration
                of your subscription.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                8. Availability and changes
              </h2>
              <p>
                We aim for high availability but the Service is provided without an
                uptime guarantee on self-serve plans. Upstream registries impose their
                own availability and rate limits that are outside our control. We may
                modify or discontinue features with reasonable notice; material
                reductions in a paid plan entitle you to a pro-rated refund of the
                unused period.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                9. Disclaimer and limitation of liability
              </h2>
              <p>
                The Service is provided &ldquo;as is&rdquo; and &ldquo;as
                available&rdquo;, without warranties of any kind, express or implied,
                including fitness for a particular purpose and non-infringement. To
                the maximum extent permitted by law, Credyx&rsquo;s aggregate
                liability arising out of or relating to the Service is limited to the
                fees you paid in the twelve months preceding the claim, and neither
                party is liable for indirect, incidental, consequential, or punitive
                damages, or for lost profits or lost data. Nothing in these Terms
                excludes liability that cannot be excluded by law.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                10. Termination
              </h2>
              <p>
                You may close your account at any time. We may suspend or terminate
                access for material breach of these Terms, non-payment, or use that
                threatens the integrity of the Service, with notice where practicable.
                Sections 5, 7, 9, and 11 survive termination. Risk assessments already
                generated remain available for export for 30 days after closure.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                11. General
              </h2>
              <p>
                These Terms are the entire agreement between you and Credyx regarding
                the Service and supersede prior agreements. If any provision is held
                unenforceable, the remainder stays in effect. We may update these
                Terms; material changes will be notified at least 30 days in advance,
                and continued use after the effective date constitutes acceptance.
                Questions about these Terms:{" "}
                <a
                  href="mailto:legal@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  legal@credyx.ai
                </a>
                .
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
