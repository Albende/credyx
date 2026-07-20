import type { NextResponse } from "next/server";

const ACCESS_COOKIE = "cl_access";
const REFRESH_COOKIE = "cl_refresh";
const ACCESS_TTL_SECONDS = 15 * 60;
const REFRESH_TTL_SECONDS = 14 * 24 * 60 * 60;

export const COOKIE_NAMES = {
  access: ACCESS_COOKIE,
  refresh: REFRESH_COOKIE,
} as const;

export const INTERNAL_API =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const SECURE = process.env.NODE_ENV === "production";

export interface BackendTokenResponse {
  access_token: string;
  refresh_token: string;
  user?: Record<string, unknown>;
  [key: string]: unknown;
}

export function setAuthCookies(
  res: NextResponse,
  tokens: { access_token: string; refresh_token: string },
): void {
  res.cookies.set({
    name: ACCESS_COOKIE,
    value: tokens.access_token,
    httpOnly: true,
    secure: SECURE,
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_TTL_SECONDS,
  });
  res.cookies.set({
    name: REFRESH_COOKIE,
    value: tokens.refresh_token,
    httpOnly: true,
    secure: SECURE,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_TTL_SECONDS,
  });
}

export function clearAuthCookies(res: NextResponse): void {
  res.cookies.set({
    name: ACCESS_COOKIE,
    value: "",
    httpOnly: true,
    secure: SECURE,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  res.cookies.set({
    name: REFRESH_COOKIE,
    value: "",
    httpOnly: true,
    secure: SECURE,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}
