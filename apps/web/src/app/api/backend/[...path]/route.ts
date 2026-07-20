import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { INTERNAL_API } from "../../auth/_helpers";

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = new URL(req.url);
  const target = `${INTERNAL_API}/api/${path.join("/")}${url.search}`;
  const store = await cookies();
  const token = store.get("cl_access")?.value;

  const headers = new Headers();
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);
  if (token) headers.set("authorization", `Bearer ${token}`);

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  const body = await upstream.arrayBuffer();
  const res = new NextResponse(body, { status: upstream.status });
  const upstreamCt = upstream.headers.get("content-type");
  if (upstreamCt) res.headers.set("content-type", upstreamCt);
  return res;
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
