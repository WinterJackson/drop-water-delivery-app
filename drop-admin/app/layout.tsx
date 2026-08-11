import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Fredoka, JetBrains_Mono, Karla } from "next/font/google";

import "./globals.css";

/**
 * Body and UI text. All default weights — Karla ships as a variable font, so
 * this is one file covering the whole 200–800 range rather than seven.
 */
const karla = Karla({ variable: "--font-karla", subsets: ["latin"] });

/**
 * Headings only, capped at 600 **on purpose**.
 *
 * Fredoka's heavier weights read as a children's brand, which is the opposite
 * of what a console handling other people's money should look like. 600 is the
 * heaviest weight this platform uses, and `font-synthesis-weight: none` in
 * `globals.css` is what stops the browser faking 700+ when a `font-bold`
 * utility lands on a heading.
 */
const fredoka = Fredoka({
  variable: "--font-fredoka",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

/**
 * Figures and code. Named `--font-jetbrains-mono`, not `--font-mono`:
 * `--font-mono` is Tailwind v4's own theme token, and pointing that token at a
 * variable of the same name on the same element is a self-reference the CSS
 * engine discards, leaving no monospace font at all. The theme token maps onto
 * this one in `globals.css`.
 */
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

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
      <html
        lang="en"
        suppressHydrationWarning
        className={`${karla.variable} ${fredoka.variable} ${jetbrainsMono.variable}`}
      >
        <body className="min-h-dvh">{children}</body>
      </html>
    </ClerkProvider>
  );
}
