import type { Metadata } from "next";
import Link from "next/link";

const TITLE = "Data Processing Agreement — Credyx";
const DESCRIPTION =
  "The data processing agreement that governs Credyx's processing of personal data on behalf of its customers.";

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

export default function DPAPage() {
  return (
    <section className="border-b border-border-default pb-24 pt-24">
      <div className="container">
        <div className="mx-auto max-w-3xl">
          <p className="serial">Legal</p>
          <h1 className="mt-3 font-display text-display-lg tracking-tight">
            Data Processing Agreement
          </h1>
          <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-fg-subtle">
            Last updated: July 2026
          </p>

          <div className="mt-8 rounded-xl border border-border-default bg-bg-elevated p-6 text-sm leading-relaxed text-fg-muted shadow-elev-1">
            This Data Processing Agreement (&ldquo;DPA&rdquo;) forms part of the
            agreement between Credyx and the customer identified in the applicable
            order or online registration (&ldquo;Customer&rdquo;) and applies wherever
            Credyx processes personal data on Customer&rsquo;s behalf. Customers who
            need a countersigned copy for their records can request one at{" "}
            <a
              href="mailto:dpa@credyx.ai"
              className="font-medium text-brand-primary underline-offset-4 hover:underline"
            >
              dpa@credyx.ai
            </a>
            .
          </div>

          <div className="mt-12 space-y-12 text-[0.95rem] leading-relaxed text-fg-muted">
            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                1. Roles and scope
              </h2>
              <p>
                For personal data contained in Customer account records, user
                profiles, and usage history (&ldquo;Customer Personal Data&rdquo;),
                Customer is the controller and Credyx acts as processor under Article
                28 GDPR. For personal data appearing in public registry records that
                Credyx retrieves and caches (such as director and officer names),
                Credyx acts as an independent controller, as described in the{" "}
                <Link
                  href="/privacy"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  privacy policy
                </Link>
                ; that processing is outside the processor scope of this DPA.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                2. Details of processing
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  <span className="font-medium text-fg-default">Subject matter and duration:</span>{" "}
                  provision of the Credyx credit intelligence service for the term of
                  the agreement.
                </li>
                <li>
                  <span className="font-medium text-fg-default">Nature and purpose:</span>{" "}
                  hosting, authentication, quota accounting, and support for
                  Customer&rsquo;s use of the platform.
                </li>
                <li>
                  <span className="font-medium text-fg-default">Categories of data subjects:</span>{" "}
                  Customer&rsquo;s authorised users.
                </li>
                <li>
                  <span className="font-medium text-fg-default">Categories of personal data:</span>{" "}
                  name, work email, hashed credentials, role, activity and billing
                  metadata. No special categories of data are processed.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                3. Processor obligations
              </h2>
              <p>Credyx shall:</p>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  process Customer Personal Data only on documented instructions from
                  Customer, including with regard to international transfers, unless
                  required otherwise by law (in which case Credyx will inform Customer
                  unless legally prohibited);
                </li>
                <li>
                  ensure persons authorised to process the data are bound by
                  confidentiality obligations;
                </li>
                <li>
                  implement the technical and organisational measures described in
                  Section 5;
                </li>
                <li>
                  assist Customer, taking into account the nature of the processing,
                  in responding to data subject requests and in meeting its
                  obligations under Articles 32–36 GDPR;
                </li>
                <li>
                  make available information reasonably necessary to demonstrate
                  compliance with Article 28 GDPR and allow for audits as set out in
                  Section 7.
                </li>
              </ul>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                4. Subprocessors
              </h2>
              <p>
                Customer grants general authorisation for Credyx to engage the
                following categories of subprocessors: cloud infrastructure and
                database hosting; content delivery and TLS termination (Cloudflare);
                transactional email delivery; payment processing; and LLM inference
                for assessment narratives (which receives company financial context,
                not Customer Personal Data). Credyx will give at least 30 days&rsquo;
                notice of any addition or replacement, during which Customer may
                object on reasonable data protection grounds. A current list is
                available on request from{" "}
                <a
                  href="mailto:dpa@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  dpa@credyx.ai
                </a>
                . Credyx remains fully liable for its subprocessors&rsquo;
                performance.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                5. Security measures
              </h2>
              <ul className="list-disc space-y-2 pl-5">
                <li>TLS encryption for all data in transit; encryption at rest for databases and backups.</li>
                <li>Salted password hashing; revocable, short-lived access tokens.</li>
                <li>Role-based access control separating administrative from standard accounts.</li>
                <li>Server-side rate limiting and per-account quotas on all endpoints.</li>
                <li>Logging of administrative and security-relevant events.</li>
              </ul>
              <p>
                Further detail is published on the{" "}
                <Link
                  href="/security"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  security page
                </Link>
                .
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                6. Personal data breaches
              </h2>
              <p>
                Credyx will notify Customer without undue delay, and in any event
                within 72 hours, after becoming aware of a personal data breach
                affecting Customer Personal Data, providing the information reasonably
                available to allow Customer to meet its own notification obligations.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                7. Audits
              </h2>
              <p>
                No more than once per year, and subject to reasonable notice and
                confidentiality obligations, Customer may audit Credyx&rsquo;s
                compliance with this DPA either through written questionnaires and
                documentation review or, where required by a supervisory authority, an
                on-site inspection conducted during business hours without disrupting
                operations.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                8. International transfers
              </h2>
              <p>
                Where processing involves a transfer of Customer Personal Data outside
                the EEA, the UK, or Switzerland to a country without an adequacy
                decision, the parties rely on the European Commission&rsquo;s Standard
                Contractual Clauses (Module 2: controller-to-processor), which are
                incorporated into this DPA by reference, supplemented by the UK
                Addendum where UK GDPR applies.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                9. Return and deletion
              </h2>
              <p>
                Upon termination of the agreement, Credyx will delete Customer
                Personal Data within 30 days, except where retention is required by
                law. Risk assessments generated for Customer remain exportable during
                that 30-day window. Deletion from backups occurs on the backup
                rotation cycle, not exceeding 90 days.
              </p>
            </div>

            <div className="space-y-4">
              <h2 className="font-display text-2xl tracking-tight text-fg-default">
                10. Precedence
              </h2>
              <p>
                In case of conflict between this DPA and the{" "}
                <Link
                  href="/terms"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  Terms of Service
                </Link>
                , this DPA prevails with respect to the processing of personal data.
                Questions:{" "}
                <a
                  href="mailto:dpa@credyx.ai"
                  className="font-medium text-brand-primary underline-offset-4 hover:underline"
                >
                  dpa@credyx.ai
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
