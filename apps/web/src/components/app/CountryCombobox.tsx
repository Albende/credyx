"use client";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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

interface PanelRect {
  left: number;
  top: number;
  width: number;
  openUp: boolean;
  maxHeight: number;
}

export function CountryCombobox({ countries, value, onChange, className }: CountryComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [mounted, setMounted] = useState(false);
  const [rect, setRect] = useState<PanelRect | null>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
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
    setMounted(true);
  }, []);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  // Position the portal panel against the trigger, flipping up when the
  // viewport bottom is close. Runs on open and on scroll/resize so the
  // fixed-position panel tracks the trigger.
  useLayoutEffect(() => {
    if (!open) return;
    function reposition() {
      const el = triggerRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const gap = 4;
      const desired = 340;
      const below = window.innerHeight - r.bottom - gap;
      const above = r.top - gap;
      const openUp = below < Math.min(desired, 240) && above > below;
      const maxHeight = Math.max(180, Math.min(desired, openUp ? above : below));
      setRect({ left: r.left, top: openUp ? r.top - gap : r.bottom + gap, width: r.width, openUp, maxHeight });
    }
    reposition();
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (panelRef.current?.contains(t)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
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

  const panel = open && mounted && rect
    ? createPortal(
        <div
          ref={panelRef}
          style={{
            position: "fixed",
            left: rect.left,
            top: rect.top,
            width: rect.width,
            transform: rect.openUp ? "translateY(-100%)" : undefined,
          }}
          className="z-[1000] overflow-hidden rounded-lg border border-border-default bg-bg-elevated shadow-elev-3"
        >
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
          <ul className="overflow-y-auto py-1" style={{ maxHeight: rect.maxHeight - 46 }}>
            {filtered.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-fg-subtle">No countries match.</li>
            ) : (
              filtered.map((c, idx) => {
                const badge = STATUS_BADGES[c.status] ?? STATUS_BADGES.error;
                const isSelected = c.country_code === value;
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
                      {isSelected && <Check className="ml-1 h-3.5 w-3.5 text-brand-primary" />}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>,
        document.body,
      )
    : null;

  return (
    <div ref={triggerRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
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
      {panel}
    </div>
  );
}
