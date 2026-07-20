import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  BackendTokenResponse,
  clearAuthCookies,
  COOKIE_NAMES,
  INTERNAL_API,
  setAuthCookies,
} from "../_helpers";

export async function POST() {
  const store = await cookies();
  const refresh = store.get(COOKIE_NAMES.refresh)?.value;
  if (!refresh) {
    return NextResponse.json({ detail: "no refresh token" }, { status: 401 });
  }

  const upstream = await fetch(`${INTERNAL_API}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
    cache: "no-store",
  });

  const text = await upstream.text();
  let parsed: unknown = text;
  try {
    parsed = JSON.parse(text);
  } catch {
    // non-JSON
  }

  if (!upstream.ok) {
    const res = NextResponse.json(
      { detail: (parsed as { detail?: string } | null)?.detail || "refresh failed" },
      { status: upstream.status },
    );
    clearAuthCookies(res);
    return res;
  }

  const tokens = parsed as BackendTokenResponse;
  if (!tokens?.access_token || !tokens?.refresh_token) {
    const res = NextResponse.json(
      { detail: "malformed backend response" },
      { status: 502 },
    );
    clearAuthCookies(res);
    return res;
  }

  const res = NextResponse.json({ ok: true });
  setAuthCookies(res, tokens);
  return res;
}
