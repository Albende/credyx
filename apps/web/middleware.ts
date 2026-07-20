import { NextResponse, type NextRequest } from "next/server";

const AUTH_PAGE = /^\/(login|register|forgot-password|reset-password)/;

function decodeBase64Url(input: string): string {
  let normalized = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = normalized.length % 4;
  if (pad === 2) normalized += "==";
  else if (pad === 3) normalized += "=";
  else if (pad === 1) throw new Error("invalid base64url");
  const binary = atob(normalized);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

interface MinimalPayload {
  role?: string;
  exp?: number;
}

function decodeToken(token: string): MinimalPayload | null {
  try {
    const segments = token.split(".");
    if (segments.length !== 3) return null;
    const payload = JSON.parse(decodeBase64Url(segments[1])) as MinimalPayload;
    if (payload.exp && payload.exp * 1000 < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const token = req.cookies.get("cl_access")?.value;
  const payload = token ? decodeToken(token) : null;
  const role = payload?.role ?? null;
  const hasSession = payload !== null;

  if (path.startsWith("/app")) {
    if (!hasSession) {
      const url = new URL("/login", req.url);
      url.searchParams.set("next", path);
      return NextResponse.redirect(url);
    }
  }

  if (path.startsWith("/admin")) {
    if (!hasSession) {
      const url = new URL("/login", req.url);
      url.searchParams.set("next", path);
      return NextResponse.redirect(url);
    }
    if (role !== "admin") {
      return NextResponse.redirect(new URL("/403", req.url));
    }
  }

  if (hasSession && AUTH_PAGE.test(path)) {
    return NextResponse.redirect(new URL("/app", req.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/app/:path*",
    "/admin/:path*",
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password/:path*",
  ],
};
