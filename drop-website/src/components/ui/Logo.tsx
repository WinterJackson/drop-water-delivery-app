import Image from "next/image";
import Link from "next/link";
import { cn } from "@/lib/utils/cn";

interface LogoProps {
  /** Desired rendered height in pixels */
  height?: number;
  className?: string;
  href?: string;
  label?: string;
}

const BASE = "inline-flex items-center";

export function Logo({
  height = 28,
  className,
  href,
  label = "Drop",
}: LogoProps) {
  const style = { height: `${height}px`, width: "auto" } as const;

  const artwork = (
    <>
      <Image
        src="/brand/drop-logo-light.png"
        alt=""
        aria-hidden
        width={120}
        height={height}
        priority
        style={{ ...style, display: "var(--logo-on-light)" }}
      />
      <Image
        src="/brand/drop-logo-dark.png"
        alt=""
        aria-hidden
        width={120}
        height={height}
        priority
        style={{ ...style, display: "var(--logo-on-dark)" }}
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
