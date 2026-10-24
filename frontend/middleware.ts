// HTTP Basic auth for the whole UI.
// - Locally: optional (enabled when ACADEMY_UI_PASSWORD is set).
// - On Vercel: mandatory. A public URL that proxies to your private library must never be open,
//   so without a password the site shows a setup notice instead of the app.
import { NextRequest, NextResponse } from "next/server";

const SETUP_PAGE = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup required</title><body style="font:16px/1.6 system-ui,sans-serif;max-width:40rem;margin:12vh auto;padding:0 1rem;color:#16202E">
<h1 style="font-size:1.4rem;color:#0E1B33">Neurosurgery AI Academy: setup required</h1>
<p>This deployment is public, so it is locked until a password is configured.</p>
<p>In Vercel, open <b>Project, Settings, Environment Variables</b>, add <code>ACADEMY_UI_PASSWORD</code>
(and optionally <code>ACADEMY_UI_USER</code>), then redeploy. Full steps: <code>docs/VERCEL.md</code>.</p></body></html>`;

export function middleware(req: NextRequest) {
  try {
    const password = process.env.ACADEMY_UI_PASSWORD;
    if (!password) {
      if (process.env.VERCEL) {
        return new NextResponse(SETUP_PAGE, { status: 503, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
      }
      return NextResponse.next();
    }
    const user = process.env.ACADEMY_UI_USER || "prof";
    const header = req.headers.get("authorization") || "";
    if (header.startsWith("Basic ")) {
      const decoded = atob(header.slice(6));
      const i = decoded.indexOf(":");
      if (i > -1 && decoded.slice(0, i) === user && decoded.slice(i + 1) === password) return NextResponse.next();
    }
    return new NextResponse("Authentication required", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="Neurosurgery AI Academy", charset="UTF-8"' },
    });
  } catch {
    return new NextResponse("Authentication required", { status: 401, headers: { "WWW-Authenticate": 'Basic realm="Neurosurgery AI Academy"' } });
  }
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
