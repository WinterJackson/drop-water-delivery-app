import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils/cn";

/**
 * The Drop wordmark, in the variant that suits the surface behind it.
 *
 * Both files are always in the markup and CSS decides which one is showing, so
 * a theme change swaps them with no re-render and no flash. The switch is
 * `display: var(--logo-on-light | --logo-on-dark)` rather than `dark:hidden`
 * because Tailwind's `dark:` variant is not wired to this console's
 * `data-theme` attribute — it would follow the operating system and ignore the
 * toggle. See the tokens in `globals.css`.
 *
 * The accessible name sits on the wrapper, never on an `<img>`: whichever image
 * is hidden is out of the accessibility tree entirely, so a name on the artwork
 * would disappear in one theme and not the other.
 */

interface LogoProps {
  height?: number;
  width?: number;
  className?: string;
  /** Makes the wordmark a link. The branding panel links home. */
  href?: string;
  /** Accessible name for the mark. */
  label?: string;
}

const RATIO = 490 / 258; // the artwork's own aspect, kept exactly

/**
 * Both branches below start from this, radius included.
 *
 * The radius used to live only on the linked branch, so the moment the branding
 * panel's wordmark stopped being a link it lost the rounding on its plate — a
 * square-cornered white rectangle on the accent panel, next to a card rounded at
 * `xl`. A shape that belongs to the mark rather than to the anchor belongs to
 * both branches; `cn` is `twMerge`, so a call site asking for a different radius
 * still wins.
 */
const BASE = "inline-flex items-center rounded-lg";

export function Logo({
  height = 40,
  width = Math.round(height * RATIO),
  className,
  href,
  label = "Drop",
}: LogoProps) {
  const artwork = (
    <>
      <Image
        src="/brand/drop-logo-light.png"
        alt=""
        aria-hidden
        width={width}
        height={height}
        priority
        className="h-auto w-auto"
        style={{ display: "var(--logo-on-light)" }}
      />
      <Image
        src="/brand/drop-logo-dark.png"
        alt=""
        aria-hidden
        width={width}
        height={height}
        priority
        className="h-auto w-auto"
        style={{ display: "var(--logo-on-dark)" }}
      />
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        aria-label={label}
        className={cn(BASE, "transition-opacity hover:opacity-80", className)}
      >
        {artwork}
      </Link>
    );
  }

  return (
    <div role="img" aria-label={label} className={cn(BASE, className)}>
      {artwork}
    </div>
  );
}
