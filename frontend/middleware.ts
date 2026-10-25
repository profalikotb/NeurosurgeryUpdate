// HTTP Basic auth for the whole UI.
// - Locally: optional (enabled when ACADEMY_UI_PASSWORD is set).
// - On Vercel: mandatory. A public URL that proxies to your private library must never be open,
//   so without a password the site shows a setup notice instead of the app.
import { NextRequest, NextResponse } from "next/server";
import { checkBasicAuth, UNAUTHORIZED_HEADERS } from "@/lib/auth";

const SETUP_PAGE = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup required</title><body style="font:16px/1.6 system-ui,sans-serif;max-width:40rem;margin:12vh auto;padding:0 1rem;color:#16202E">
<h1 style="font-size:1.4rem;color:#0E1B33">Neurosurgery AI Academy: setup required</h1>
<p>This deployment is public, so it is locked until a password is configured.</p>
<p>Add the environment variable <code>ACADEMY_UI_PASSWORD</code> (Render: service, <b>Environment</b>;
Vercel: <b>Settings, Environment Variables</b>), save, and let the service redeploy.</p></body></html>`;

export function middleware(req: NextRequest) {
  const r = checkBasicAuth(req.headers.get("authorization"));
  if (r === "ok") return NextResponse.next();
  if (r === "setup") {
    return new NextResponse(SETUP_PAGE, { status: 503, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
  }
  return new NextResponse("Authentication required", { status: 401, headers: UNAUTHORIZED_HEADERS });
}

// The upload route is excluded here (Next.js would buffer and truncate large request bodies in middleware);
// it performs the same password check itself.
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico|healthz|api/backend/library/upload).*)"] };
