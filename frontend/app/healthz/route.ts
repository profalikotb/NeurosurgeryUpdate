// Public health check for the hosting platform (no password, no data). Reports whether the backend answers.
export const dynamic = "force-dynamic";

export async function GET() {
  const backend = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  try {
    const r = await fetch(`${backend}/api/health`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    return Response.json({ web: "ok", backend: r.ok ? "ok" : `HTTP ${r.status}` }, { status: r.ok ? 200 : 503 });
  } catch {
    return Response.json({ web: "ok", backend: "starting" }, { status: 503 });
  }
}
