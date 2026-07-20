"use client";

import * as React from "react";

export type ThemeSelection = "system" | "light" | "dark";
export type EffectiveTheme = "light" | "dark";

const STORAGE_KEY = "cl-theme";
const COOKIE_KEY = "cl-theme";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;
const AUTH_COOKIE = "cl_access";

function readStoredSelection(): ThemeSelection {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "system" || v === "light" || v === "dark") return v;
  } catch {
    /* ignore */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return true;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveEffective(selection: ThemeSelection): EffectiveTheme {
  if (selection === "system") return systemPrefersDark() ? "dark" : "light";
  return selection;
}

function applyEffective(effective: EffectiveTheme) {
  const root = document.documentElement;
  root.classList.toggle("dark", effective === "dark");
  root.style.colorScheme = effective;
}

type DocumentWithViewTransition = Document & {
  startViewTransition?: (update: () => void) => { finished: Promise<void> };
};

/* Pulls the new theme down over the old one like a window shade
   (see the theme-slide rules in globals.css). */
function applyEffectiveWithSlide(effective: EffectiveTheme) {
  const doc = document as DocumentWithViewTransition;
  const isDark = document.documentElement.classList.contains("dark");
  if ((effective === "dark") === isDark) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || reduceMotion) {
    applyEffective(effective);
    return;
  }
  const root = document.documentElement;
  root.classList.add("theme-slide");
  const transition = doc.startViewTransition(() => {
    applyEffective(effective);
    const edge = document.createElement("div");
    edge.className = "theme-shade-edge";
    edge.setAttribute("aria-hidden", "true");
    document.body.appendChild(edge);
    window.setTimeout(() => edge.remove(), 800);
  });
  const cleanup = () => root.classList.remove("theme-slide");
  transition.finished.then(cleanup, cleanup);
}

function writeCookie(value: ThemeSelection) {
  try {
    document.cookie = `${COOKIE_KEY}=${value}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
  } catch {
    /* ignore */
  }
}

function writeStorage(value: ThemeSelection) {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* ignore */
  }
}

function hasAuthCookie(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.split(";").some((c) => c.trim().startsWith(`${AUTH_COOKIE}=`));
}

function patchBackendPreference(theme: ThemeSelection) {
  if (!hasAuthCookie()) return;
  try {
    void fetch("/api/backend/auth/me/preferences", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme }),
      credentials: "include",
    }).catch(() => {
      /* ignore */
    });
  } catch {
    /* ignore */
  }
}

export interface UseThemeResult {
  selection: ThemeSelection;
  effective: EffectiveTheme;
  setTheme: (next: ThemeSelection) => void;
}

export function useTheme(): UseThemeResult {
  const [selection, setSelection] = React.useState<ThemeSelection>("system");
  const [effective, setEffective] = React.useState<EffectiveTheme>("dark");

  React.useEffect(() => {
    const stored = readStoredSelection();
    const eff = resolveEffective(stored);
    setSelection(stored);
    setEffective(eff);
    applyEffective(eff);
  }, []);

  React.useEffect(() => {
    if (selection !== "system") return;
    if (typeof window === "undefined") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      const eff: EffectiveTheme = e.matches ? "dark" : "light";
      setEffective(eff);
      applyEffectiveWithSlide(eff);
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [selection]);

  const setTheme = React.useCallback((next: ThemeSelection) => {
    const eff = resolveEffective(next);
    setSelection(next);
    setEffective(eff);
    applyEffectiveWithSlide(eff);
    writeStorage(next);
    writeCookie(next);
    patchBackendPreference(next);
  }, []);

  return { selection, effective, setTheme };
}
