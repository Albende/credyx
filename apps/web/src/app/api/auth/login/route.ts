import { NextResponse } from "next/server";
import {
  BackendTokenResponse,
  INTERNAL_API,
  setAuthCookies,
} from "../_helpers";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  const upstream = await fetch(`${INTERNAL_API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const text = await upstream.text();
  let parsed: unknown = text;
  try {
    parsed = JSON.parse(text);
  } catch {
    // non-JSON response
  }

  if (!upstream.ok) {
    const detail =
      (parsed as { detail?: string } | null)?.detail || `HTTP ${upstream.status}`;
    return NextResponse.json({ detail }, { status: upstream.status });
  }

  const tokens = parsed as BackendTokenResponse;
  if (!tokens?.access_token || !tokens?.refresh_token) {
    return NextResponse.json(
      { detail: "Malformed token response from backend" },
      { status: 502 },
    );
  }

  const res = NextResponse.json({ user: tokens.user ?? null });
  setAuthCookies(res, tokens);
  return res;
}
