const API_BASE = "";

const INTERNAL_API =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const PUBLIC_API_PATHS = new Set([
  "/api/countries",
  "/api/health",
  "/api/billing/plans",
]);

export type Capabilities = { search: boolean; lookup: boolean; financials: boolean };

export type CountryHealth = {
  country_code: string;
  name: string;
  status: "ok" | "degraded" | "not_implemented" | "blocked" | "error";
  capabilities: Capabilities;
  requires_api_key: boolean;
  api_key_present: boolean;
  notes?: string | null;
};

export type RegistryIdentifier = { type: string; value: string; label?: string };

export type CompanyMatch = {
  id: string;
  name: string;
  country: string;
  identifiers: RegistryIdentifier[];
  address?: string | null;
  status?: string | null;
  source_url?: string | null;
};

export type CompanyDetails = {
  id: string;
  name: string;
  country: string;
  legal_form?: string | null;
  status?: string | null;
  incorporation_date?: string | null;
  registered_address?: string | null;
  capital_amount?: number | null;
  capital_currency?: string | null;
  sic_codes?: string[];
  nace_codes?: string[];
  identifiers: RegistryIdentifier[];
  directors?: { name: string; role?: string | null; appointed_on?: string | null }[];
  source_url?: string | null;
};

export type FinancialFiling = {
  year: number;
  type: string;
  period_end?: string | null;
  currency?: string | null;
  structured_data?: Record<string, unknown> | null;
  document_url?: string | null;
  document_format?: string | null;
  source_url?: string | null;
};

export type RiskAssessment = {
  score: number;
  recommendation: "APPROVE" | "REVIEW" | "REJECT";
  recommended_credit_limit_eur: number;
  reasoning: string;
  key_signals: string[];
  red_flags: string[];
  confidence: number;
  model_used?: string | null;
  ratios?: Array<Record<string, number | null | string>>;
};

export type Job<T = unknown> = {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  result?: T | null;
  error?: string | null;
};

function rewriteForBrowser(path: string): string {
  if (typeof window === "undefined") return path;
  if (PUBLIC_API_PATHS.has(path.split("?")[0])) return path;
  if (path.startsWith("/api/")) return "/api/backend/" + path.slice(5);
  return path;
}

async function serverHeaders(): Promise<Record<string, string>> {
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

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const isServer = typeof window === "undefined";
  const base = isServer ? INTERNAL_API : "";
  const finalPath = rewriteForBrowser(path);
  const authHeaders = isServer ? await serverHeaders() : {};
  const res = await fetch(`${base}${finalPath}`, {
    cache: "no-store",
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...authHeaders,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} on ${path}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  countries: () => http<{ countries: CountryHealth[] }>("/api/countries"),
  search: (country: string, name: string, limit = 10) =>
    http<{ country: string; query: string; results: CompanyMatch[] }>(
      `/api/search?country=${encodeURIComponent(country)}&name=${encodeURIComponent(name)}&limit=${limit}`,
    ),
  company: (country: string, identifier: string, opts?: { force?: boolean }) =>
    http<{ cached: boolean; last_fetched_at: string | null; details: CompanyDetails }>(
      `/api/companies/${country}/${encodeURIComponent(identifier)}${opts?.force ? "?force_refresh=true" : ""}`,
    ),
  financials: (country: string, identifier: string, opts?: { force?: boolean }) =>
    http<{ filings: FinancialFiling[]; cached: boolean }>(
      `/api/companies/${country}/${encodeURIComponent(identifier)}/financials${opts?.force ? "?force_refresh=true" : ""}`,
    ),
  startRisk: (country: string, identifier: string) =>
    http<{ job_id: string; status: string }>(
      `/api/companies/${country}/${encodeURIComponent(identifier)}/risk-analysis`,
      { method: "POST" },
    ),
  job: (jobId: string) => http<Job<RiskAssessment>>(`/api/jobs/${jobId}`),
};
