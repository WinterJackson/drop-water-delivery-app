import Image from "next/image";

import { ParticlesBackground } from "@/components/auth/ParticlesBackground";
import { ThemedSignIn } from "@/components/auth/ThemedSignIn";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { Logo } from "@/components/ui/Logo";

export const metadata = { title: "Sign in" };

/**
 * The only public page in the console.
 *
 * The sign-up affordance is hidden on purpose, and there is no `/sign-up` route
 * to link to. Administrators are invited by an existing administrator and bound
 * to their Clerk account on first sign-in; there is no self-service path into
 * `Admin_Users`, so offering "create an account" here would only ever produce a
 * customer account that lands on "you don't have access" — and it puts a
 * registration form on the privileged origin for no reason. A test in
 * `test_admin_console_frontend.py` fails the build if that route becomes public.
 *
 * A session alone proves nothing here. Every screen behind this one asks the
 * backend who the caller is, against `Admin_Users`, on every request.
 *
 * Every colour on this page comes from a semantic token, so the branding panel,
 * the particle field and the form all move together between themes. Nothing is
 * `dark:`-prefixed: that variant follows the operating system rather than the
 * console's `data-theme`, and would ignore the toggle sitting in the corner.
 */
export default function SignInPage() {
  return (
    <div className="relative flex min-h-dvh w-full flex-col overflow-hidden md:flex-row">
      {/* ── Branding panel ──────────────────────────────────────────────
          Hidden below md. It carries no information the operator needs to
          sign in, so dropping it on a phone costs nothing but decoration. */}
      <aside className="relative z-10 hidden flex-col bg-accent p-8 md:flex md:w-1/2 lg:p-12">
        {/* The wordmark is blue in both its variants, so it needs its own
            light plate to read against the accent panel — inverting the file
            would show the same blue mark either way.

            Not a link. Every route behind this one is protected, so `/` sends
            an unauthenticated visitor straight back here — a control whose only
            effect is to reload the page it is on. */}
        <div className="flex-none">
          {/* `rounded-xl`, the same radius as the sign-in card opposite it, so
              the two plates on this screen read as one set. */}
          <Logo height={34} className="rounded-xl bg-surface px-4 py-3 shadow-sm" />
        </div>

        <div className="flex flex-1 items-center justify-center p-8">
          <div className="relative aspect-square w-full max-w-md drop-shadow-2xl">
            <Image
              src="/brand/dropy-hero.webp"
              alt=""
              aria-hidden
              fill
              sizes="(max-width: 768px) 0vw, 50vw"
              quality={90}
              className="object-contain"
              priority
            />
          </div>
        </div>

        <div className="max-w-lg flex-none space-y-4 text-accent-foreground">
          <h1 className="text-4xl font-semibold tracking-tight lg:text-5xl">
            The whole business, on one screen.
          </h1>
          <p className="text-lg opacity-80">
            Orders, riders, vendors, payouts and disputes — read from the same
            database the three apps use, so a figure here and a figure in a
            vendor&rsquo;s app cannot drift apart.
          </p>
        </div>
      </aside>

      {/* ── Form panel ──────────────────────────────────────────────────── */}
      <main className="relative z-10 flex w-full flex-1 items-stretch justify-center bg-[var(--background)] p-4 md:w-1/2">
        {/* Decoration, behind everything and inert to the pointer except the
            particle canvas itself, which is what makes it interactive. */}
        <div className="absolute inset-0 z-0 bg-[var(--background)]">
          <ParticlesBackground />
        </div>

        <div className="absolute right-4 top-4 z-20">
          <ThemeToggle />
        </div>

        {/* Three rows, the outer two an equal `1fr`, so the card in the middle
            sits on the panel's exact centre line whatever the heading above and
            the note below happen to weigh. Centring the column as a whole does
            not do this: the note is taller than the heading, which left the
            card riding high — and the card is what the eye centres on. */}
        <div className="relative z-10 grid w-full max-w-md grid-rows-[1fr_auto_1fr] py-4">
          <div className="flex flex-col justify-end pb-6">
            {/* The branding panel is hidden here, so the mark comes back above
                the form — a sign-in page with no identity on it is a phishing
                page as far as the person reading it can tell. */}
            <div className="mb-8 flex justify-center md:hidden">
              <Logo height={38} />
            </div>

            <div className="text-center">
              <h2 className="text-2xl font-semibold tracking-tight">Drop Admin</h2>
              <p className="mt-1 text-sm text-muted">
                Operations console. Administrator access only.
              </p>
            </div>
          </div>

          <ThemedSignIn />

          <div className="pt-6">
            <p className="mx-auto max-w-sm text-center text-xs text-muted">
              Access is granted by an existing administrator, and two-factor
              authentication is required.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
