import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Building2,
  FileText,
  Globe2,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import { getSession } from "@/lib/auth";
import { FLAGS } from "@/lib/countries";
import { SmartSearch } from "@/components/app/SmartSearch";
import { Reveal } from "@/components/ui/reveal";
import { BentoCard } from "@/components/ui/bento-card";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { Sparkline } from "@/components/ui/sparkline";
import { BadgeLive } from "@/components/ui/badge-live";
import { AuroraText } from "@/components/ui/aurora-text";

export const dynamic = "force-dynamic";

const REGION_GROUPS: { label: string; codes: string[]; accent: string }[] = [
  {
    label: "Europe",
    codes: [
      "GB", "FR", "DE", "NL", "IT", "ES", "BE", "SE", "NO", "DK", "FI", "IE",
      "AT", "CZ", "PL", "PT", "GR", "HU", "RO", "BG", "HR", "SI", "LT", "LV", "EE",
    ],
    accent: "from-brand-primary/20 to-brand-primary/0",
  },
  {
    label: "Americas",
    codes: ["US", "CA", "MX", "BR", "AR", "CL", "CO", "PE"],
    accent: "from-accent/20 to-accent/0",
  },
  {
    label: "Asia-Pacific",
    codes: ["JP", "KR", "SG", "HK", "TW", "AU", "NZ", "ID", "MY", "TH", "VN", "PH", "IN", "CN"],
    accent: "from-brand-secondary/20 to-brand-secondary/0",
  },
  {
    label: "MENA + Africa",
    codes: ["AE", "SA", "IL", "EG", "ZA", "NG", "KE", "MA", "TR"],
    accent: "from-success/15 to-success/0",
  },
];

export default async function AppDashboard() {
  const session = await getSession();
  let countries: Awaited<ReturnType<typeof api.countries>>["countries"] = [];
  let error: string | null = null;
  try {
    const data = await api.countries();
    countries = data.countries;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const usable = countries.filter((c) => c.status === "ok" || c.status === "degraded");
  const total = countries.length;
  const coveragePct = total > 0 ? Math.round((usable.length / total) * 100) : 0;
  const liveCount = countries.filter((c) => c.status === "ok").length;

  const featured = ["GB", "US", "FR", "DE", "NL", "PL", "IT", "ES"]
    .map((cc) => countries.find((c) => c.country_code === cc))
    .filter((c): c is NonNullable<typeof c> => Boolean(c))
    .slice(0, 4);

  const firstName = session?.first_name?.trim();

  // Decorative micro-chart series
  const coverageTrend = [4, 6, 7, 9, 12, 14, 18, 22, 27, 31, 35, liveCount || 38];
  const reportsTrend = [2, 5, 4, 7, 9, 6, 11, 8, 13, 10, 14, 12];
  const quotaUsed = 3;
  const quotaTotal = 10;
  const quotaPct = Math.min(100, Math.round((quotaUsed / quotaTotal) * 100));

  return (
    <div className="space-y-10">
      {/* Eyebrow + greeting */}
      <Reveal as="header" className="space-y-2">
        <div className="flex items-center gap-2 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-brand-primary">
          <Sparkles className="h-3.5 w-3.5" />
          Dashboard
          <span className="h-px w-10 bg-gradient-to-r from-brand-primary/60 to-transparent" />
        </div>
        <h1 className="font-display text-3xl font-semibold tracking-tight md:text-[2.6rem] md:leading-[1.05]">
          {firstName ? (
            <>
              Welcome back,{" "}
              <AuroraText className="font-display">{firstName}</AuroraText>
            </>
          ) : (
            <>
              Welcome to <AuroraText className="font-display">Credyx</AuroraText>
            </>
          )}
        </h1>
        <p className="max-w-2xl text-sm text-fg-muted md:text-[0.95rem]">
          Search live registries, pull filed financials, and run audit-ready credit risk
          analyses — across {liveCount}+ live country adapters.
        </p>
      </Reveal>

      {/* Hero search panel */}
      <Reveal>
        <div className="relative overflow-hidden rounded-2xl border border-border-default/80 bg-bg-elevated/60 p-6 shadow-depth-2 backdrop-blur-xl">
          {/* Mesh accent backdrop */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 opacity-80"
            style={{
              background:
                "radial-gradient(540px circle at 12% 0%, hsl(var(--color-brand-primary) / 0.14), transparent 55%), radial-gradient(420px circle at 100% 100%, hsl(var(--color-accent) / 0.12), transparent 60%)",
            }}
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent"
          />
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <BadgeLive label="LIVE" />
              <span className="font-mono text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-fg-subtle">
                Smart search
              </span>
            </div>
            <Link
              href="/app/search"
              className="group inline-flex items-center gap-1 text-xs font-medium text-brand-primary"
            >
              Advanced search
              <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>
          {error ? (
            <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
              Could not load adapters: {error}
            </div>
          ) : (
            <SmartSearch countries={countries} />
          )}
        </div>
      </Reveal>

      {/* KPI bento — 4 unequal cards */}
      <Reveal>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-6 lg:grid-rows-2">
          {/* Live countries — tall left tile */}
          <BentoCard
            span="lg:col-span-2 lg:row-span-2"
            eyebrow="Coverage"
            title="Live countries"
            icon={<Globe2 className="h-4 w-4" />}
          >
            <div className="flex items-end justify-between gap-4">
              <div>
                <div className="font-display text-5xl font-semibold tracking-tight">
                  <AnimatedCounter value={liveCount} />
                </div>
                <div className="mt-1 text-xs text-fg-muted">
                  {coveragePct}% of {total} adapters
                </div>
              </div>
              <BadgeLive label="LIVE" />
            </div>
            <div className="mt-6">
              <Sparkline
                data={coverageTrend}
                width={280}
                height={56}
                color="hsl(var(--color-brand-primary))"
                fill
                className="w-full text-brand-primary"
              />
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-border-default/60 pt-3 text-[11px] text-fg-subtle">
              <span className="font-mono uppercase tracking-[0.14em]">Trailing 12 months</span>
              <span className="inline-flex items-center gap-1 text-success">
                <ArrowUpRight className="h-3 w-3" /> +{Math.max(0, liveCount - 4)}
              </span>
            </div>
          </BentoCard>

          {/* Companies indexed */}
          <BentoCard
            span="lg:col-span-2"
            eyebrow="Indexed"
            title="Companies"
            icon={<Building2 className="h-4 w-4" />}
          >
            <div className="font-display text-4xl font-semibold tracking-tight">
              <AnimatedCounter value={8} />
              <span className="text-brand-primary">M+</span>
            </div>
            <div className="mt-1 text-xs text-fg-muted">Across all live registries</div>
          </BentoCard>

          {/* Plan — small top-right */}
          <BentoCard
            span="lg:col-span-2"
            eyebrow="Subscription"
            title="Current plan"
            icon={<TrendingUp className="h-4 w-4" />}
          >
            <div className="flex items-baseline justify-between">
              <span className="font-display text-3xl font-semibold tracking-tight">Free</span>
              <span className="text-xs font-medium text-fg-muted tabular-nums">
                {quotaUsed} / {quotaTotal}
              </span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bg-inset">
              <span
                className="block h-full rounded-full bg-gradient-to-r from-brand-primary via-accent to-brand-secondary"
                style={{ width: `${quotaPct}%` }}
              />
            </div>
            <Link
              href="/app/account/subscription"
              className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-brand-primary"
            >
              Upgrade <ArrowRight className="h-3 w-3" />
            </Link>
          </BentoCard>

          {/* Risk reports — wide bottom-right */}
          <BentoCard
            span="lg:col-span-4"
            eyebrow="Activity"
            title="Risk reports run"
            icon={<FileText className="h-4 w-4" />}
          >
            <div className="flex items-end justify-between gap-6">
              <div>
                <div className="font-display text-4xl font-semibold tracking-tight">
                  <AnimatedCounter value={0} />
                </div>
                <Link
                  href="/app/search"
                  className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-primary"
                >
                  Run your first one
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
              {/* Mini bar chart */}
              <div className="flex h-12 items-end gap-1">
                {reportsTrend.map((v, i) => {
                  const max = Math.max(...reportsTrend);
                  const h = Math.max(8, (v / max) * 100);
                  return (
                    <span
                      key={i}
                      className="w-2 rounded-sm bg-gradient-to-t from-brand-primary/30 to-brand-primary/80"
                      style={{ height: `${h}%` }}
                    />
                  );
                })}
              </div>
            </div>
          </BentoCard>
        </div>
      </Reveal>

      {/* Featured registries */}
      <Reveal as="section" className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <div className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-fg-subtle">
              Featured
            </div>
            <h2 className="font-display text-lg font-semibold tracking-tight">
              Top registries
            </h2>
          </div>
          <Link
            href="/app/coverage"
            className="group inline-flex items-center gap-1 text-xs font-medium text-brand-primary"
          >
            See all {total}
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {featured.map((c) => {
            const live = c.status === "ok";
            return (
              <Link
                key={c.country_code}
                href={`/app/search?country=${c.country_code}`}
                className="group relative overflow-hidden rounded-2xl border border-border-default/80 bg-bg-elevated/60 p-5 backdrop-blur-sm transition-all duration-300 hover:-translate-y-1 hover:border-brand-primary/40 hover:shadow-depth-2"
              >
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
                  style={{
                    background:
                      "radial-gradient(280px circle at 50% 0%, hsl(var(--color-brand-primary) / 0.18), transparent 65%)",
                  }}
                />
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent"
                />
                <div className="relative flex items-start justify-between">
                  <span className="text-3xl leading-none">
                    {FLAGS[c.country_code] ?? "🏳️"}
                  </span>
                  <span
                    className={
                      "h-1.5 w-1.5 rounded-full " +
                      (live
                        ? "bg-success shadow-[0_0_8px_hsl(var(--color-success)/0.7)]"
                        : "bg-warning")
                    }
                    title={c.status}
                  />
                </div>
                <div className="relative mt-4">
                  <div className="font-display text-base font-semibold tracking-tight">
                    {c.country_code}
                  </div>
                  <div className="mt-0.5 truncate text-xs text-fg-muted">{c.name}</div>
                </div>
                <div className="relative mt-4 flex items-center gap-3 border-t border-border-default/50 pt-3">
                  <CapPill ok={c.capabilities.search} label="Search" />
                  <CapPill ok={c.capabilities.lookup} label="Lookup" />
                  <CapPill ok={c.capabilities.financials} label="Financials" />
                </div>
              </Link>
            );
          })}
        </div>
      </Reveal>

      {/* Region breakdown — 2 columns */}
      <Reveal as="section" className="space-y-4">
        <div className="flex items-end justify-between">
          <div className="space-y-0.5">
            <div className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-fg-subtle">
              By region
            </div>
            <h2 className="font-display text-lg font-semibold tracking-tight">
              Global coverage map
            </h2>
          </div>
          <Link
            href="/app/coverage"
            className="group inline-flex items-center gap-1 text-xs font-medium text-brand-primary"
          >
            Explore coverage
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {REGION_GROUPS.map((region) => {
            const inRegion = region.codes
              .map((cc) => countries.find((c) => c.country_code === cc))
              .filter((c): c is NonNullable<typeof c> => Boolean(c));
            const live = inRegion.filter(
              (c) => c.status === "ok" || c.status === "degraded",
            ).length;
            const pct = inRegion.length > 0 ? Math.round((live / inRegion.length) * 100) : 0;
            return (
              <div
                key={region.label}
                className="group relative overflow-hidden rounded-2xl border border-border-default/80 bg-bg-elevated/60 p-5 backdrop-blur-sm transition-colors hover:border-border-strong"
              >
                <div
                  aria-hidden
                  className={`pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b ${region.accent}`}
                />
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent"
                />
                <div className="relative mb-4 flex items-start justify-between">
                  <div>
                    <h3 className="font-display text-base font-semibold tracking-tight">
                      {region.label}
                    </h3>
                    <p className="mt-0.5 text-[11px] text-fg-muted tabular-nums">
                      {live} live · {inRegion.length} adapters · {pct}%
                    </p>
                  </div>
                  <div className="relative h-9 w-9">
                    <svg viewBox="0 0 36 36" className="h-9 w-9 -rotate-90">
                      <circle
                        cx="18"
                        cy="18"
                        r="15"
                        fill="none"
                        stroke="hsl(var(--border-default))"
                        strokeWidth="3"
                      />
                      <circle
                        cx="18"
                        cy="18"
                        r="15"
                        fill="none"
                        stroke="hsl(var(--color-brand-primary))"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeDasharray={`${(pct / 100) * 94.25} 94.25`}
                      />
                    </svg>
                  </div>
                </div>
                <div className="relative flex flex-wrap gap-1.5">
                  {inRegion.map((c) => {
                    const isLive = c.status === "ok" || c.status === "degraded";
                    return (
                      <Link
                        key={c.country_code}
                        href={`/app/search?country=${c.country_code}`}
                        title={`${c.name} — ${c.status}`}
                        className={
                          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-all duration-200 hover:-translate-y-0.5 " +
                          (isLive
                            ? "border-success/30 bg-success/10 text-success hover:border-success/50 hover:bg-success/15"
                            : "border-border-default/70 bg-bg-overlay/60 text-fg-subtle hover:bg-bg-overlay")
                        }
                      >
                        <span className="leading-none">{FLAGS[c.country_code] ?? "🏳️"}</span>
                        {c.country_code}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </Reveal>
    </div>
  );
}

function CapPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={
          "h-1.5 w-1.5 rounded-full " +
          (ok
            ? "bg-success shadow-[0_0_6px_hsl(var(--color-success)/0.6)]"
            : "bg-bg-overlay")
        }
      />
      <span className="text-[10px] font-medium uppercase tracking-wider text-fg-subtle">
        {label}
      </span>
    </div>
  );
}
