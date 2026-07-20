import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  clearAuthCookies,
  COOKIE_NAMES,
  INTERNAL_API,
} from "../_helpers";

export async function POST() {
  const store = await cookies();
  const refresh = store.get(COOKIE_NAMES.refresh)?.value;

  await fetch(`${INTERNAL_API}/api/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ refresh_token: refresh ?? null }),
    cache: "no-store",
  }).catch(() => undefined);

  const res = NextResponse.json({ ok: true });
  clearAuthCookies(res);
  return res;
}
