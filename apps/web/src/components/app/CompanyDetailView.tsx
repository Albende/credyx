"use client";
import { useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Building2,
  Calendar,
  ChevronRight,
  Clock,
  Coins,
  Copy,
  ExternalLink,
  FileText,
  Hash,
  MapPin,
  RefreshCw,
  Sparkles,
  Users,
} from "lucide-react";
import { api, type CompanyDetails, type FinancialFiling } from "@/lib/api";
import { FLAGS } from "@/lib/countries";
import { cn } from "@/lib/utils";
import { MeshGradient } from "@/components/ui/mesh-gradient";
import { fadeUp, outExpo, staggerContainer } from "@/lib/motion";
import { RiskAnalysisPanel } from "./RiskAnalysisPanel";

interface Props {
  country: string;
  identifier: string;
  details: CompanyDetails;
  cached: boolean;
  filings: FinancialFiling[];
  financialsCached: boolean;
  lastFetchedAt: string | null;
}

type Tab = "overview" | "financials" | "risk" | "directors";

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "overview", label: "Overview", icon: Building2 },
  { id: "financials", label: "Financials", icon: FileText },
  { id: "risk", label: "Risk analysis", icon: Sparkles },
  { id: "directors", label: "Directors", icon: Users },
];

export function CompanyDetailView({
  country,
  identifier,
  details,
  cached,
  filings,
  lastFetchedAt,
}: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try {
      await api.company(country, identifier, { force: true });
      window.location.reload();
    } catch {
      setRefreshing(false);
    }
  }

  const directorsCount = details.directors?.length ?? 0;

  return (
    <div className="space-y-6">
      <Link
        href="/app/search"
        className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition hover:text-fg-default"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to search
      </Link>

      <header className="relative isolate overflow-hidden rounded-lg border border-border-default bg-bg-elevated p-7">
        <MeshGradient intensity="normal" className="rounded-lg" />

        <div className="relative flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
          <div className="flex items-start gap-4 min-w-0">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-bg-overlay text-4xl leading-none ring-1 ring-border-default">
              {FLAGS[country] ?? "🏳️"}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-brand-primary">
                <span>{country}</span>
                <ChevronRight className="h-3 w-3" />
                <span className="text-fg-muted">{identifier}</span>
              </div>
              <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight md:text-3xl break-words">
                {details.name}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {details.status && (
                  <Pill tone={details.status === "active" ? "success" : "warn"}>{details.status}</Pill>
                )}
                {details.legal_form && <Pill tone="neutral">{details.legal_form}</Pill>}
                {details.incorporation_date && (
                  <Pill tone="neutral">
                    <Calendar className="mr-1 inline h-3 w-3" />
                    incorporated {details.incorporation_date}
                  </Pill>
                )}
                {cached && (
                  <Pill tone="muted">
                    <Clock className="mr-1 inline h-3 w-3" /> cached{lastFetchedAt ? ` · ${new Date(lastFetchedAt).toLocaleDateString()}` : ""}
                  </Pill>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {details.source_url && (
              <a
                href={details.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default px-3 py-2 text-xs font-medium text-fg-muted transition hover:bg-bg-overlay"
              >
                Open registry <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            <button
              onClick={refresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default px-3 py-2 text-xs font-medium text-fg-muted transition hover:bg-bg-overlay disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /> Refresh
            </button>
            <button
              onClick={() => setTab("risk")}
              className="inline-flex items-center gap-1.5 rounded-md bg-brand-primary px-3 py-2 text-xs font-semibold text-brand-primary-fg transition hover:bg-brand-primary/90"
            >
              <Sparkles className="h-3.5 w-3.5" /> Run risk analysis
            </button>
          </div>
        </div>
      </header>

      <div className="relative flex flex-wrap gap-1 border-b border-border-default">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          const count =
            t.id === "financials" ? filings.length : t.id === "directors" ? directorsCount : undefined;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition -mb-px",
                active
                  ? "text-fg-default"
                  : "text-fg-muted hover:text-fg-default",
              )}
            >
              <Icon className="h-4 w-4" />
              {t.label}
              {count !== undefined && (
                <span className="rounded-md bg-bg-overlay px-1.5 py-0.5 text-[10px] tabular-nums text-fg-subtle">
                  {count}
                </span>
              )}
              {active && (
                <motion.span
                  layoutId="company-tab-underline"
                  className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-primary shadow-[0_0_12px_hsl(var(--color-brand-primary)/0.6)]"
                  transition={{ type: "spring", stiffness: 380, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>

      <div>
        {tab === "overview" && <OverviewTab details={details} country={country} />}
        {tab === "financials" && (
          <FinancialsTab country={country} identifier={identifier} filings={filings} />
        )}
        {tab === "risk" && (
          <RiskAnalysisPanel country={country} identifier={identifier} companyName={details.name} />
        )}
        {tab === "directors" && <DirectorsTab directors={details.directors ?? []} />}
      </div>
    </div>
  );
}

function OverviewTab({ details, country }: { details: CompanyDetails; country: string }) {
  const facts: Array<{
    label: string;
    value?: string | null;
    icon: React.ComponentType<{ className?: string }>;
    numeric?: boolean;
  }> = [
    { label: "Country", value: country, icon: MapPin },
    { label: "Legal form", value: details.legal_form, icon: Building2 },
    { label: "Incorporated", value: details.incorporation_date, icon: Calendar, numeric: true },
    { label: "Status", value: details.status, icon: Sparkles },
    {
      label: "Capital",
      value:
        details.capital_amount != null
          ? `${details.capital_amount.toLocaleString("en-US")} ${details.capital_currency ?? ""}`
          : null,
      icon: Coins,
      numeric: true,
    },
  ];

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <div className="rounded-lg border border-border-default bg-bg-elevated p-5">
          <div className="mb-4 text-xs font-medium uppercase tracking-wider text-fg-muted">Registry facts</div>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            {facts
              .filter((f) => f.value)
              .map((f) => {
                const Icon = f.icon;
                return (
                  <div key={f.label} className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md bg-brand-primary/10 text-brand-primary">
                      <Icon className="h-3.5 w-3.5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[11px] uppercase tracking-wider text-fg-subtle">{f.label}</div>
                      <div className={cn("mt-0.5 text-sm text-fg-default", f.numeric && "tabular-nums")}>
                        {f.value}
                      </div>
                    </div>
                  </div>
                );
              })}
          </dl>
        </div>

        {details.registered_address && (
          <div className="rounded-lg border border-border-default bg-bg-elevated p-5">
            <div className="mb-3 flex items-center gap-2">
              <MapPin className="h-4 w-4 text-brand-primary" />
              <div className="text-sm font-semibold tracking-tight">Registered address</div>
            </div>
            <div className="rounded-lg bg-bg-base px-4 py-3 text-sm text-fg-default">{details.registered_address}</div>
          </div>
        )}

        {((details.nace_codes?.length ?? 0) + (details.sic_codes?.length ?? 0) > 0) && (
          <div className="rounded-lg border border-border-default bg-bg-elevated p-5">
            <div className="mb-3 text-xs font-medium uppercase tracking-wider text-fg-muted">Industry codes</div>
            <div className="flex flex-wrap gap-2">
              {details.nace_codes?.map((c) => (
                <span key={`nace-${c}`} className="rounded-md border border-border-default bg-bg-base px-2.5 py-1 text-xs font-mono text-fg-default">
                  NACE {c}
                </span>
              ))}
              {details.sic_codes?.map((c) => (
                <span key={`sic-${c}`} className="rounded-md border border-border-default bg-bg-base px-2.5 py-1 text-xs font-mono text-fg-default">
                  SIC {c}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-5">
        <div className="relative overflow-hidden rounded-lg border border-border-default bg-bg-elevated/60 p-5 shadow-elev-1 backdrop-blur-xl">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-gradient-to-br from-brand-primary/[0.06] via-transparent to-brand-secondary/[0.04]"
          />
          <div className="relative mb-3 flex items-center gap-2">
            <Hash className="h-4 w-4 text-brand-primary" />
            <div className="text-sm font-semibold tracking-tight">Identifiers</div>
          </div>
          <ul className="relative space-y-2">
            {details.identifiers.map((id, i) => (
              <li
                key={i}
                className="group relative cursor-pointer overflow-hidden rounded-lg border border-border-default/60 bg-bg-base/60 px-3 py-2 backdrop-blur-sm transition-all duration-200 hover:border-brand-primary/40 hover:bg-bg-base/90 hover:shadow-[0_0_0_1px_hsl(var(--color-brand-primary)/0.25)]"
                title="Click to copy"
              >
                <div className="text-[10px] uppercase tracking-wider text-fg-subtle">{id.label || id.type}</div>
                <div className="mt-0.5 flex items-center justify-between gap-2">
                  <span className="font-mono text-sm tabular-nums text-fg-default break-all">{id.value}</span>
                  <Copy className="h-3.5 w-3.5 shrink-0 text-fg-subtle opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
                </div>
              </li>
            ))}
          </ul>
        </div>

        {details.source_url && (
          <div className="rounded-lg border border-border-default bg-bg-elevated p-5">
            <div className="text-xs font-medium uppercase tracking-wider text-fg-muted">Source</div>
            <a
              href={details.source_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 flex items-center gap-1.5 text-sm text-brand-primary hover:underline"
            >
              Official registry record <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function FinancialsTab({
  country,
  identifier,
  filings,
}: {
  country: string;
  identifier: string;
  filings: FinancialFiling[];
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [current, setCurrent] = useState<FinancialFiling[]>(filings);

  async function refresh() {
    setRefreshing(true);
    try {
      const data = await api.financials(country, identifier, { force: true });
      setCurrent(data.filings);
    } finally {
      setRefreshing(false);
    }
  }

  if (current.length === 0) {
    const externalUrl = externalFilingsUrl(country, identifier);
    return (
      <div className="rounded-lg border border-dashed border-border-default bg-bg-elevated p-10 text-center">
        <FileText className="mx-auto h-8 w-8 text-fg-subtle" />
        <div className="mt-3 text-sm font-medium">No filings retrieved through the API</div>
        <p className="mx-auto mt-1 max-w-lg text-xs text-fg-muted">
          {externalUrl
            ? "This registry publishes annual financial statements on a separate portal protected by a bot wall. Click the deep-link below to view them on the official site."
            : "Either this country adapter does not yet implement financials, or the source returned none. Try refreshing — some sources hydrate filings lazily."}
        </p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            onClick={refresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default px-3 py-2 text-xs font-medium transition hover:bg-bg-overlay"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /> Refresh
          </button>
          {externalUrl && (
            <a
              href={externalUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-2 text-xs font-medium text-brand-primary-fg transition hover:brightness-110"
            >
              Open official filings <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          {current.length} filings on record
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-default px-2.5 py-1 text-xs font-medium text-fg-muted transition hover:bg-bg-overlay"
        >
          <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} /> Refresh
        </button>
      </div>

      <div className="overflow-hidden rounded-lg border border-border-default bg-bg-elevated">
        <motion.ul
          className="divide-y divide-border-default"
          variants={staggerContainer}
          initial="hidden"
          animate="show"
        >
          {current.map((f, i) => (
            <motion.li
              key={i}
              variants={fadeUp}
              transition={{ duration: 0.45, ease: outExpo }}
              className="group relative p-4 transition-colors duration-200 hover:bg-bg-overlay/60"
            >
              <div className="relative flex flex-wrap items-center gap-3">
                <div className="flex h-10 min-w-[3.5rem] flex-col items-center justify-center rounded-md border border-brand-primary/40 bg-brand-primary/10 px-2 text-brand-primary transition-colors duration-200 group-hover:border-brand-primary/70 group-hover:bg-brand-primary/15">
                  <div className="font-display text-base font-semibold leading-none tabular-nums">{f.year}</div>
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium">{(f.type || "").replace(/_/g, " ")}</div>
                  <div className="text-[11px] tabular-nums text-fg-muted">
                    {(() => {
                      const sd = (f.structured_data ?? {}) as Record<string, unknown>;
                      const period = sd.period as string | undefined;
                      const msigNum = sd.msig_number as string | undefined;
                      const msigPage = sd.msig_page as number | undefined;
                      const parts = [
                        period ? `fiscal ${period}` : null,
                        f.currency || null,
                        f.document_format ? f.document_format.toUpperCase() : null,
                        msigNum ? `MSiG ${msigNum}${msigPage ? ` p.${msigPage}` : ""}` : null,
                      ].filter(Boolean);
                      return parts.join(" · ");
                    })()}
                  </div>
                </div>
                <div className="ml-auto flex items-center gap-1.5">
                  {f.document_url ? (
                    <a
                      href={f.document_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-2.5 py-1 text-xs font-semibold text-brand-primary-fg transition-all duration-200 hover:brightness-110 hover:shadow-glow-brand"
                    >
                      Download <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : f.source_url ? (
                    <a
                      href={f.source_url}
                      target="_blank"
                      rel="noreferrer"
                      title="Opens the official registry — your browser solves the bot challenge automatically"
                      className="inline-flex items-center gap-1 rounded-md bg-brand-primary/15 px-2.5 py-1 text-xs font-semibold text-brand-primary transition-all duration-200 hover:bg-brand-primary/25 hover:shadow-glow-brand"
                    >
                      Open in registry <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}
                </div>
              </div>
              {f.structured_data && Object.keys(f.structured_data).length > 0 && (
                <details className="relative mt-3 rounded-lg bg-bg-base p-3">
                  <summary className="cursor-pointer text-xs text-fg-muted">Structured data</summary>
                  <pre className="mt-2 overflow-x-auto text-[11px] tabular-nums text-fg-muted">
                    {JSON.stringify(f.structured_data, null, 2)}
                  </pre>
                </details>
              )}
            </motion.li>
          ))}
        </motion.ul>
      </div>
    </div>
  );
}

function externalFilingsUrl(country: string, identifier: string): string | null {
  const id = encodeURIComponent(identifier);
  switch (country) {
    case "PL":
      return `https://ekrs.ms.gov.pl/rdf/pd/search_df?nr_krs=${id}`;
    case "GB":
    case "UK":
      return `https://find-and-update.company-information.service.gov.uk/company/${id}/filing-history`;
    case "US":
      return `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${id}&type=&dateb=&owner=include&count=40`;
    case "FR":
      return `https://www.pappers.fr/entreprise/${id}`;
    case "CZ":
      return `https://or.justice.cz/ias/ui/rejstrik-$firma?ico=${id}`;
    case "DE":
      return `https://www.handelsregister.de/rp_web/result.xhtml`;
    case "NL":
      return `https://www.kvk.nl/zoeken/?source=all&q=${id}`;
    case "IT":
      return `https://www.registroimprese.it`;
    case "ES":
      return `https://www.boe.es/diario_borme/`;
    case "SE":
      return `https://www.allabolag.se`;
    default:
      return null;
  }
}

function DirectorsTab({
  directors,
}: {
  directors: { name: string; role?: string | null; appointed_on?: string | null }[];
}) {
  if (directors.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border-default bg-bg-elevated p-10 text-center">
        <Users className="mx-auto h-8 w-8 text-fg-subtle" />
        <div className="mt-3 text-sm font-medium">No director data available</div>
        <p className="mt-1 text-xs text-fg-muted">This adapter does not expose officer lists.</p>
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {directors.map((d, i) => (
        <div key={i} className="rounded-lg border border-border-default bg-bg-elevated p-4">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-primary/15 text-xs font-semibold text-brand-primary">
              {d.name
                .split(" ")
                .map((w) => w[0])
                .slice(0, 2)
                .join("")
                .toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{d.name}</div>
              {d.role && <div className="mt-0.5 text-xs text-fg-muted">{d.role}</div>}
              {d.appointed_on && (
                <div className="mt-1 text-[11px] text-fg-subtle">Appointed {d.appointed_on}</div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Pill({
  tone,
  children,
}: {
  tone: "success" | "warn" | "muted" | "neutral";
  children: React.ReactNode;
}) {
  const cls =
    tone === "success"
      ? "bg-success/15 text-success ring-success/30"
      : tone === "warn"
        ? "bg-warning/15 text-warning ring-warning/30"
        : tone === "muted"
          ? "bg-bg-overlay text-fg-subtle ring-border-default"
          : "bg-bg-overlay text-fg-muted ring-border-default";
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${cls}`}>
      {children}
    </span>
  );
}
