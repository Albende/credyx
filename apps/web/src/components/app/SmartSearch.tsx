"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Building2, ExternalLink, Loader2 } from "lucide-react";
import { CountryCombobox } from "./CountryCombobox";
import { api, type CompanyMatch, type CountryHealth } from "@/lib/api";
import { FLAGS, IDENTIFIER_LABELS } from "@/lib/countries";
import { cn } from "@/lib/utils";

type Mode = "name" | "identifier";

interface SmartSearchProps {
  countries: CountryHealth[];
  compact?: boolean;
  defaultCountry?: string;
}

export function SmartSearch({ countries, compact = false, defaultCountry }: SmartSearchProps) {
  const router = useRouter();
  const usable = useMemo(
    () => countries.filter((c) => c.status === "ok" || c.status === "degraded"),
    [countries],
  );
  const [country, setCountry] = useState<string>(defaultCountry ?? usable[0]?.country_code ?? "GB");
  const [mode, setMode] = useState<Mode>("name");
  const [value, setValue] = useState("");
  const [results, setResults] = useState<CompanyMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const labels = IDENTIFIER_LABELS[country] ?? { primary: "Identifier", placeholder: "" };
  const selectedCountry = countries.find((c) => c.country_code === country);
  const countryUsable = selectedCountry?.status === "ok" || selectedCountry?.status === "degraded";

  useEffect(() => {
    setResults([]);
    setErr(null);
  }, [country, mode]);

  useEffect(() => {
    if (mode !== "name") return;
    const q = value.trim();
    if (q.length < 2) {
      setResults([]);
      setErr(null);
      return;
    }
    let cancelled = false;
    const handle = setTimeout(async () => {
      setLoading(true);
      setErr(null);
      try {
        const data = await api.search(country, q);
        if (!cancelled) setResults(data.results);
      } catch (e) {
        if (!cancelled) {
          setResults([]);
          setErr(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [value, country, mode]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (mode === "identifier" && value.trim()) {
      router.push(`/app/company/${country}/${encodeURIComponent(value.trim())}`);
    }
  }

  return (
    <div className="space-y-4">
      <div className={cn("rounded-lg border border-border-default bg-bg-elevated p-4 shadow-elev-1", compact ? "p-3" : "p-4")}>
        <div className="flex flex-wrap items-stretch gap-2">
          <div className="w-full min-w-0 sm:w-72">
            <CountryCombobox countries={countries} value={country} onChange={setCountry} />
          </div>

          <div className="flex flex-1 items-stretch overflow-hidden rounded-lg border border-border-default bg-bg-elevated focus-within:border-brand-primary/60 focus-within:ring-2 focus-within:ring-brand-primary/30">
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={
                mode === "name"
                  ? `Search ${selectedCountry?.name ?? country} companies by name…`
                  : `Lookup by ${labels.primary} (${labels.placeholder || "identifier"})`
              }
              className="flex-1 bg-transparent px-3.5 py-2.5 text-sm placeholder:text-fg-subtle focus:outline-none"
              onKeyDown={(e) => {
                if (e.key === "Enter" && mode === "identifier" && value.trim()) {
                  submit(e as unknown as React.FormEvent);
                }
              }}
            />
            <button
              type="button"
              onClick={(e) => submit(e as unknown as React.FormEvent)}
              disabled={!value.trim() || (mode === "name" && loading)}
              className="flex items-center gap-1.5 bg-brand-primary px-4 text-sm font-medium text-brand-primary-fg transition hover:brightness-110 disabled:opacity-40"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              {mode === "name" ? "Search" : "Look up"}
            </button>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-1.5 text-xs">
          <button
            type="button"
            onClick={() => setMode("name")}
            className={cn(
              "rounded-md px-2.5 py-1 transition",
              mode === "name"
                ? "bg-brand-primary/15 text-brand-primary"
                : "text-fg-muted hover:bg-bg-overlay hover:text-fg-default",
            )}
          >
            By name
          </button>
          <button
            type="button"
            onClick={() => setMode("identifier")}
            className={cn(
              "rounded-md px-2.5 py-1 transition",
              mode === "identifier"
                ? "bg-brand-primary/15 text-brand-primary"
                : "text-fg-muted hover:bg-bg-overlay hover:text-fg-default",
            )}
          >
            By {labels.primary}
          </button>
          {!countryUsable && (
            <span className="ml-auto rounded-md bg-warning/10 px-2 py-1 text-warning">
              {selectedCountry?.status === "not_implemented" ? "Adapter coming soon" : "This adapter is unavailable"}
            </span>
          )}
        </div>
      </div>

      {err && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {err}
        </div>
      )}

      {results.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border-default bg-bg-elevated">
          <div className="flex items-center justify-between border-b border-border-default px-4 py-2.5">
            <span className="text-xs font-medium uppercase tracking-wider text-fg-muted">
              {results.length} {results.length === 1 ? "match" : "matches"} in {selectedCountry?.name ?? country}
            </span>
            <span className="text-base leading-none">{FLAGS[country] ?? "🌍"}</span>
          </div>
          <ul className="divide-y divide-border-default">
            {results.map((r) => (
              <li key={r.id}>
                <a
                  href={`/app/company/${country}/${encodeURIComponent(r.id)}`}
                  className="flex items-start gap-3 px-4 py-3 transition hover:bg-bg-overlay"
                >
                  <div className="mt-0.5 rounded-lg bg-brand-primary/10 p-2 text-brand-primary">
                    <Building2 className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium">{r.name}</div>
                    <div className="mt-0.5 truncate text-xs text-fg-muted">
                      {r.identifiers.map((i) => `${i.label || i.type}: ${i.value}`).join(" · ")}
                      {r.address ? ` · ${r.address}` : ""}
                    </div>
                  </div>
                  {r.status && (
                    <span className="shrink-0 rounded-md bg-success/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-success">
                      {r.status}
                    </span>
                  )}
                  <ExternalLink className="ml-1 h-4 w-4 shrink-0 self-center text-fg-subtle" />
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
