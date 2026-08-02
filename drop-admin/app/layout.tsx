import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Drop Admin", template: "%s · Drop Admin" },
  description: "Operations console for the Drop water delivery platform.",
  // This console lists customers and renders identity documents. It must never
  // appear in a search index, and referrers must not leak record ids.
  robots: { index: false, follow: false, nocache: true },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#12181f" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" suppressHydrationWarning>
        <body className="min-h-dvh">{children}</body>
      </html>
    </ClerkProvider>
  );
}
