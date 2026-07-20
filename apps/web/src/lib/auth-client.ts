"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "./api-client";

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: "user" | "admin";
  email_verified: boolean;
  plan_slug?: string;
}

export interface UseAuthResult {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

export function useAuth(): UseAuthResult {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const me = await apiFetch<User>("/api/auth/me");
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const signOut = useCallback(async () => {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include",
    }).catch(() => undefined);
    setUser(null);
    window.location.href = "/";
  }, []);

  return { user, loading, refresh: load, signOut };
}

/** Standalone signOut for non-hook contexts (e.g. AdminShell sign-out button). */
export async function signOut(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => undefined);
  if (typeof window !== "undefined") window.location.href = "/";
}
