"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { FLAGS } from "@/lib/countries";
import { cn } from "@/lib/utils";
import type { CountryHealth } from "@/lib/api";

interface CountryComboboxProps {
  countries: CountryHealth[];
  value: string;
  onChange: (cc: string) => void;
  className?: string;
}

const STATUS_BADGES: Record<string, { label: string; cls: string }> = {
  ok: { label: "live", cls: "bg-success/15 text-success" },
  degraded: { label: "needs key", cls: "bg-warning/15 text-warning" },
  not_implemented: { label: "soon", cls: "bg-bg-overlay text-fg-subtle" },
  blocked: { label: "blocked", cls: "bg-danger/15 text-danger" },
  error: { label: "error", cls: "bg-danger/15 text-danger" },
};

export function CountryCombobox({ countries, value, onChange, className }: CountryComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = countries.find((c) => c.country_code === value);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const sorted = [...countries].sort((a, b) => {
      const aOk = a.status === "ok" ? 0 : a.status === "degraded" ? 1 : 2;
      const bOk = b.status === "ok" ? 0 : b.status === "degraded" ? 1 : 2;
      if (aOk !== bOk) return aOk - bOk;
      return a.name.localeCompare(b.name);
    });
    if (!q) return sorted;
    return sorted.filter(
      (c) =>
        c.country_code.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q),
    );
  }, [countries, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  function pick(cc: string) {
    onChange(cc);
    setOpen(false);
    setQuery("");
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[activeIndex];
      if (item) pick(item.country_code);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={ref} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border-default bg-bg-elevated px-3 py-2.5 text-left text-sm transition hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-brand-primary/40"
      >
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="text-lg leading-none">{FLAGS[selected?.country_code ?? ""] ?? "🌍"}</span>
          <span className="truncate">
            {selected ? (
              <>
                <span className="font-medium">{selected.country_code}</span>
                <span className="text-fg-muted"> — {selected.name}</span>
              </>
            ) : (
              <span className="text-fg-muted">Select country…</span>
            )}
          </span>
        </span>
        <ChevronsUpDown className="h-4 w-4 text-fg-subtle" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 overflow-hidden rounded-lg border border-border-default bg-bg-elevated shadow-elev-2">
          <div className="flex items-center gap-2 border-b border-border-default px-3 py-2">
            <Search className="h-4 w-4 text-fg-subtle" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Type country code or name…"
              className="w-full bg-transparent text-sm placeholder:text-fg-subtle focus:outline-none"
            />
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-fg-subtle">No countries match.</li>
            ) : (
              filtered.map((c, idx) => {
                const badge = STATUS_BADGES[c.status] ?? STATUS_BADGES.error;
                const selected = c.country_code === value;
                const active = idx === activeIndex;
                return (
                  <li key={c.country_code}>
                    <button
                      type="button"
                      onClick={() => pick(c.country_code)}
                      onMouseEnter={() => setActiveIndex(idx)}
                      className={cn(
                        "flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition",
                        active && "bg-bg-overlay",
                      )}
                    >
                      <span className="text-base leading-none">{FLAGS[c.country_code] ?? "🏳️"}</span>
                      <span className="flex-1 truncate">
                        <span className="font-medium">{c.country_code}</span>
                        <span className="ml-1.5 text-fg-muted">{c.name}</span>
                      </span>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider", badge.cls)}>
                        {badge.label}
                      </span>
                      {selected && <Check className="ml-1 h-3.5 w-3.5 text-brand-primary" />}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
