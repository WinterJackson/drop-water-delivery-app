import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The dashboard renders national ID photographs from short-lived presigned S3
  // URLs. Next's image optimiser would fetch and *cache* them on the server,
  // which turns a 5-minute link into a copy of somebody's identity document
  // sitting in the build cache. Every such image is rendered `unoptimized`.
  images: { remotePatterns: [{ protocol: "https", hostname: "**.amazonaws.com" }] },
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // This console is never a legitimate embed target, and every page of
          // it is privileged.
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
};

export default nextConfig;
