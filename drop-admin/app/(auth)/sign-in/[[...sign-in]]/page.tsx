import { SignIn } from "@clerk/nextjs";

export const metadata = { title: "Sign in" };

/**
 * The only public page in the console.
 *
 * The sign-up affordance is hidden on purpose. Administrators are invited by an
 * existing administrator and bound to their Clerk account on first sign-in;
 * there is no self-service path into `Admin_Users`, so offering "create an
 * account" here would only ever produce a customer account that lands on "you
 * don't have access" — and it puts a registration form on the admin origin for
 * no reason.
 *
 * A session alone proves nothing here. Every screen behind this one asks the
 * backend who the caller is, against `Admin_Users`, on every request.
 */
export default function SignInPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-8 px-4 py-12">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Drop Admin</h1>
        <p className="mt-1 text-sm text-muted">
          Operations console. Administrator access only.
        </p>
      </div>

      <SignIn appearance={{ elements: { footerAction: { display: "none" } } }} />

      <p className="max-w-sm text-center text-xs text-muted">
        Access is granted by an existing administrator, and two-factor
        authentication is required.
      </p>
    </main>
  );
}
