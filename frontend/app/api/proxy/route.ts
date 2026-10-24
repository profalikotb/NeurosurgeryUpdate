// Server-side proxy to the FastAPI backend. The browser calls /api/backend/<path>; next.config.mjs rewrites that
// to /api/proxy?__path=<path> (a catch-all folder name like [...path] breaks GitHub's web uploader). The API token lives only in server env vars;
// the browser talks to /api/backend/* and never sees it.
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const BACKEND = (process.env.BACKEND_URL || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
const TOKEN = (process.env.ACADEMY_API_TOKEN || "").trim();
const ON_VERCEL = !!process.env.VERCEL;
// content-length / content-encoding are NOT forwarded: fetch() already decompressed the body, so a forwarded
// length from a gzip-ing tunnel (Cloudflare, ngrok) would not match and corrupt the response.
const PASS_HEADERS = ["content-type", "content-disposition", "cache-control", "etag", "last-modified", "accept-ranges", "content-range"];

const fail = (status: number, detail: string) => Response.json({ detail }, { status, headers: { "cache-control": "no-store" } });

async function proxy(req: NextRequest) {
  try {
    if (ON_VERCEL && /^https?:\/\/(localhost|127\.|0\.0\.0\.0|\[::1\])/i.test(BACKEND)) {
      return fail(503, "BACKEND_URL points to localhost, which Vercel cannot reach. The backend runs on the PC that holds the books; expose it with a tunnel and set BACKEND_URL in Vercel (see docs/VERCEL.md).");
    }
    if (!TOKEN) return fail(503, "ACADEMY_API_TOKEN is not set for the frontend.");
    // Route handlers see the original URL (/api/backend/<path>) after the rewrite; __path is a fallback for
    // hosts that expose the rewritten destination instead.
    const params = new URLSearchParams(req.nextUrl.search);
    const PREFIX = "/api/backend/";
    const raw = req.nextUrl.pathname.startsWith(PREFIX) ? req.nextUrl.pathname.slice(PREFIX.length) : params.get("__path") || "";
    params.delete("__path");
    const path = raw.split("/").filter(Boolean).map((p) => decodeURIComponent(p));
    if (!path.length || path.some((p) => p === ".." || p === "." || p.includes("\\") || p.includes("/"))) return fail(400, "bad path");

    const qs = params.toString();
    const url = `${BACKEND}/api/${path.map(encodeURIComponent).join("/")}${qs ? `?${qs}` : ""}`;
    const headers = new Headers({ "X-Academy-Token": TOKEN, accept: req.headers.get("accept") || "*/*" });
    const ct = req.headers.get("content-type");
    if (ct) headers.set("content-type", ct);
    const range = req.headers.get("range");
    if (range) headers.set("range", range);
    const hasBody = !["GET", "HEAD"].includes(req.method);

    let upstream: Response;
    try {
      upstream = await fetch(url, {
        method: req.method,
        headers,
        body: hasBody ? await req.arrayBuffer() : undefined,
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(55_000),
      });
    } catch (e) {
      const why = e instanceof Error && e.name === "TimeoutError" ? "timed out" : "unreachable";
      return fail(502, `Backend ${why} at ${BACKEND}. Is the backend (and tunnel, if remote) running?`);
    }
    const out = new Headers();
    for (const h of PASS_HEADERS) {
      const v = upstream.headers.get(h);
      if (v) out.set(h, v);
    }
    if (upstream.status === 401) {
      return fail(502, "The backend rejected the API token: ACADEMY_API_TOKEN differs between frontend and backend.");
    }
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch (e) {
    return fail(500, `Proxy error: ${e instanceof Error ? e.message : String(e)}`);
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE };
