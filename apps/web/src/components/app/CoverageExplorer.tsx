"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, Globe2 } from "lucide-react";
import { FLAGS } from "@/lib/countries";
import type { CountryHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

type StatusFilter = "all" | "live" | "soon" | "blocked";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  ok: { label: "live", cls: "bg-success/15 text-success border-success/30" },
  degraded: { label: "needs key", cls: "bg-warning/15 text-warning border-warning/30" },
  not_implemented: { label: "soon", cls: "bg-bg-overlay text-fg-subtle border-border-default" },
  blocked: { label: "blocked", cls: "bg-danger/15 text-danger border-danger/30" },
  error: { label: "error", cls: "bg-danger/15 text-danger border-danger/30" },
};

export function CoverageExplorer({ countries }: { countries: CountryHealth[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [capabilities, setCapabilities] = useState<{ search: boolean; lookup: boolean; financials: boolean }>({
    search: false,
    lookup: false,
    financials: false,
  });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return countries
      .filter((c) => {
        if (q) {
          if (
            !c.country_code.toLowerCase().includes(q) &&
            !c.name.toLowerCase().includes(q)
          ) {
            return false;
          }
        }
        if (status === "live" && !(c.status === "ok" || c.status === "degraded")) return false;
        if (status === "soon" && c.status !== "not_implemented") return false;
        if (status === "blocked" && c.status !== "blocked" && c.status !== "error") return false;
        if (capabilities.search && !c.capabilities.search) return false;
        if (capabilities.lookup && !c.capabilities.lookup) return false;
        if (capabilities.financials && !c.capabilities.financials) return false;
        return true;
      })
      .sort((a, b) => {
        const aLive = a.status === "ok" || a.status === "degraded";
        const bLive = b.status === "ok" || b.status === "degraded";
        if (aLive !== bLive) return aLive ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
  }, [countries, query, status, capabilities]);

  const counts = useMemo(() => {
    let live = 0;
    let soon = 0;
    let blocked = 0;
    for (const c of countries) {
      if (c.status === "ok" || c.status === "degraded") live++;
      else if (c.status === "not_implemented") soon++;
      else blocked++;
    }
    return { live, soon, blocked, total: countries.length };
  }, [countries]);

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-border-default bg-bg-elevated p-4">
        <div className="flex items-center gap-2 rounded-lg border border-border-default bg-bg-base px-3 py-2.5">
          <Search className="h-4 w-4 text-fg-subtle" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search countries by ISO code or name…"
            className="w-full bg-transparent text-sm placeholder:text-fg-subtle focus:outline-none"
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <FilterChip active={status === "all"} onClick={() => setStatus("all")}>
            All <span className="text-fg-subtle">· {counts.total}</span>
          </FilterChip>
          <FilterChip active={status === "live"} onClick={() => setStatus("live")} tone="success">
            Live <span className="opacity-70">· {counts.live}</span>
          </FilterChip>
          <FilterChip active={status === "soon"} onClick={() => setStatus("soon")} tone="muted">
            Soon <span className="opacity-70">· {counts.soon}</span>
          </FilterChip>
          <FilterChip active={status === "blocked"} onClick={() => setStatus("blocked")} tone="danger">
            Blocked <span className="opacity-70">· {counts.blocked}</span>
          </FilterChip>

          <span className="ml-2 hidden h-5 w-px bg-border-default md:block" />

          <CapToggle
            active={capabilities.search}
            onClick={() => setCapabilities((c) => ({ ...c, search: !c.search }))}
          >
            Search
          </CapToggle>
          <CapToggle
            active={capabilities.lookup}
            onClick={() => setCapabilities((c) => ({ ...c, lookup: !c.lookup }))}
          >
            Lookup
          </CapToggle>
          <CapToggle
            active={capabilities.financials}
            onClick={() => setCapabilities((c) => ({ ...c, financials: !c.financials }))}
          >
            Financials
          </CapToggle>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-border-default bg-bg-elevated p-12 text-center">
          <Globe2 className="mx-auto h-8 w-8 text-fg-subtle" />
          <p className="mt-3 text-sm text-fg-muted">No countries match those filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((c) => {
            const meta = STATUS_META[c.status] ?? STATUS_META.error;
            const isLive = c.status === "ok" || c.status === "degraded";
            return (
              <Link
                key={c.country_code}
                href={isLive ? `/app/search?country=${c.country_code}` : "#"}
                className={cn(
                  "group flex items-start gap-3 rounded-xl border border-border-default bg-bg-elevated p-3.5 transition",
                  isLive ? "hover:border-brand-primary/40" : "cursor-default opacity-70",
                )}
              >
                <span className="text-2xl leading-none">{FLAGS[c.country_code] ?? "🏳️"}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold">{c.country_code}</div>
                      <div className="truncate text-xs text-fg-muted">{c.name}</div>
                    </div>
                    <span className={cn("shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider", meta.cls)}>
                      {meta.label}
                    </span>
                  </div>
                  <div className="mt-2.5 flex items-center gap-2 text-[10px] uppercase tracking-wider text-fg-subtle">
                    <Cap ok={c.capabilities.search}>Search</Cap>
                    <Cap ok={c.capabilities.lookup}>Lookup</Cap>
                    <Cap ok={c.capabilities.financials}>Financials</Cap>
                  </div>
                  {c.notes && (
                    <div className="mt-2 line-clamp-2 text-[11px] text-fg-subtle">{c.notes}</div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  tone = "brand",
  children,
}: {
  active: boolean;
  onClick: () => void;
  tone?: "brand" | "success" | "muted" | "danger";
  children: React.ReactNode;
}) {
  const toneCls = active
    ? tone === "success"
      ? "bg-success/20 text-success border-success/40"
      : tone === "muted"
        ? "bg-bg-overlay text-fg-default border-border-strong"
        : tone === "danger"
          ? "bg-danger/20 text-danger border-danger/40"
          : "bg-brand-primary/20 text-brand-primary border-brand-primary/40"
    : "border-border-default text-fg-muted hover:bg-bg-overlay";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("rounded-md border px-2.5 py-1 text-xs font-medium transition", toneCls)}
    >
      {children}
    </button>
  );
}

function CapToggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border px-2.5 py-1 text-xs transition",
        active
          ? "border-brand-primary/40 bg-brand-primary/10 text-brand-primary"
          : "border-border-default text-fg-muted hover:bg-bg-overlay",
      )}
    >
      {children}
    </button>
  );
}

function Cap({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className={cn("flex items-center gap-1", ok ? "text-success" : "text-fg-subtle")}>
      <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-success" : "bg-bg-overlay")} />
      {children}
    </span>
  );
}
