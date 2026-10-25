/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // No next/image optimisation is used; avoids shipping the native sharp binary in the Windows package.
  images: { unoptimized: true },
  output: process.env.NEXT_STANDALONE === "1" ? "standalone" : undefined,
  async rewrites() {
    return [{ source: "/api/backend/:path*", destination: "/api/proxy?__path=:path*" }];
  },
  async headers() {
    return [{
      source: "/(.*)",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "X-Frame-Options", value: "SAMEORIGIN" },
      ],
    }];
  },
};
export default nextConfig;
