import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export interface Session {
  user_id: string;
  id: string;
  role: "user" | "admin";
  email: string;
  first_name: string;
  last_name: string;
  is_verified?: boolean;
  email_verified?: boolean;
}

interface JwtPayload {
  sub: string;
  role: "user" | "admin";
  email: string;
  first_name?: string;
  last_name?: string;
  email_verified?: boolean;
  exp?: number;
}

function decodeBase64Url(input: string): string {
  let normalized = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = normalized.length % 4;
  if (pad === 2) normalized += "==";
  else if (pad === 3) normalized += "=";
  else if (pad === 1) throw new Error("invalid base64url");
  return Buffer.from(normalized, "base64").toString("utf8");
}

export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  const token = store.get("cl_access")?.value;
  if (!token) return null;
  try {
    const segments = token.split(".");
    if (segments.length !== 3) return null;
    const payload = JSON.parse(decodeBase64Url(segments[1])) as JwtPayload;
    if (payload.exp && payload.exp * 1000 < Date.now()) return null;
    if (!payload.sub || !payload.role) return null;
    return {
      user_id: payload.sub,
      id: payload.sub,
      role: payload.role,
      email: payload.email ?? "",
      first_name: payload.first_name ?? "",
      last_name: payload.last_name ?? "",
      is_verified: payload.email_verified,
      email_verified: payload.email_verified,
    };
  } catch {
    return null;
  }
}

export async function requireSession(): Promise<Session> {
  const s = await getSession();
  if (!s) redirect("/login");
  return s;
}

export async function requireAdmin(): Promise<Session> {
  const s = await requireSession();
  if (s.role !== "admin") redirect("/403");
  return s;
}
