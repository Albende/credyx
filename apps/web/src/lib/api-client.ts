const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const INTERNAL_API = process.env.INTERNAL_API_URL || API_BASE;

function rewriteForBrowser(path: string): string {
  if (typeof window === "undefined") return path;
  if (path.startsWith("/api/auth/login") || path.startsWith("/api/auth/logout") || path.startsWith("/api/auth/refresh")) {
    return path;
  }
  if (path.startsWith("/api/")) {
    return "/api/backend/" + path.slice(5);
  }
  return path;
}

export class ApiError extends Error {
  status: number;
  body?: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }
}

export interface ApiFetchInit extends RequestInit {
  skipAuth?: boolean;
  serverSide?: boolean;
}

function pickBase(init?: ApiFetchInit): string {
  const isServer = init?.serverSide ?? typeof window === "undefined";
  if (isServer) return INTERNAL_API;
  return "";
}

function buildHeaders(init?: ApiFetchInit): HeadersInit {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(init?.headers || {}),
  };
}

async function serverAuthHeader(): Promise<Record<string, string>> {
  if (typeof window !== "undefined") return {};
  try {
    const mod = await import("next/headers");
    const store = await mod.cookies();
    const token = store.get("cl_access")?.value;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export async function apiFetch<T>(path: string, init?: ApiFetchInit): Promise<T> {
  const base = pickBase(init);
  const isServer = init?.serverSide ?? typeof window === "undefined";
  const authHeaders = isServer ? await serverAuthHeader() : {};
  const requestInit: RequestInit = {
    cache: "no-store",
    credentials: "include",
    ...init,
    headers: { ...buildHeaders(init), ...authHeaders },
  };

  const res = await fetch(`${base}${rewriteForBrowser(path)}`, requestInit);

  if (res.status === 401 && !init?.skipAuth && typeof window !== "undefined") {
    const refreshed = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) {
      const retry = await fetch(`${base}${rewriteForBrowser(path)}`, {
        ...requestInit,
        credentials: "include",
        cache: "no-store",
      });
      if (retry.ok) {
        return (await retry.json()) as T;
      }
    }
    const next = encodeURIComponent(window.location.pathname);
    window.location.href = `/login?next=${next}`;
    throw new ApiError(401, "redirect");
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      // body is not JSON; keep text
    }
    const detail =
      (parsed as { detail?: string } | null)?.detail ||
      (typeof parsed === "string" ? parsed : `HTTP ${res.status}`);
    throw new ApiError(res.status, detail, parsed);
  }

  return (await res.json()) as T;
}
