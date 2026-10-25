// Shared HTTP Basic-auth check, used by the middleware and by the upload route (which bypasses the middleware
// so that large books are streamed instead of being buffered by Next.js).
export type AuthResult = "ok" | "unauthorized" | "setup";

export function checkBasicAuth(header: string | null): AuthResult {
  const password = process.env.ACADEMY_UI_PASSWORD;
  if (!password) return process.env.VERCEL || process.env.ACADEMY_REQUIRE_PASSWORD ? "setup" : "ok";
  const user = process.env.ACADEMY_UI_USER || "prof";
  if (header?.startsWith("Basic ")) {
    try {
      const decoded = atob(header.slice(6));
      const i = decoded.indexOf(":");
      if (i > -1 && decoded.slice(0, i) === user && decoded.slice(i + 1) === password) return "ok";
    } catch {
      /* malformed header */
    }
  }
  return "unauthorized";
}

export const UNAUTHORIZED_HEADERS = { "WWW-Authenticate": 'Basic realm="Neurosurgery AI Academy", charset="UTF-8"' };
