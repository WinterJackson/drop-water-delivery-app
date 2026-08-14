import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The dashboard renders national ID photographs from short-lived presigned S3
  // URLs. Next's image optimiser would fetch and *cache* them on the server,
  // which turns a 5-minute link into a copy of somebody's identity document
  // sitting in the build cache. Every such image is rendered `unoptimized`.
  images: {
    remotePatterns: [{ protocol: "https", hostname: "**.amazonaws.com" }],
    // Every `quality` an <Image> is allowed to ask for. Next 16 stopped
    // honouring arbitrary values: the quality is part of the optimiser's cache
    // key and reachable from the query string, so an open range lets anybody
    // mint a hundred re-encodes of the same file. Unlisted values are ignored
    // with a warning and served at the default instead — the sign-in hero asked
    // for 90 and was silently getting 75.
    //
    // 75 is the default and covers everything. 90 is the branding artwork on
    // the sign-in page, which is `priority` and the largest thing on that
    // screen; it is one 41 KB decorative WebP, so the extra bytes buy a crisp
    // first impression on the only page signed-out administrators ever see.
    qualities: [75, 90],
  },
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
