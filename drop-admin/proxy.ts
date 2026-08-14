import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

/**
 * The request gate in front of every route on this origin.
 *
 * This is the file Next.js used to call `middleware.ts`. Next 16 renamed the
 * convention to `proxy.ts` — same position in the request lifecycle, same
 * default export, same `config.matcher` — and warns on every boot while the old
 * name is still on disk. Only the *file* is renamed: `clerkMiddleware` keeps its
 * name, and Clerk finds itself through a header it sets rather than through the
 * filename, so nothing downstream cares.
 *
 * One thing did change and it is the reason not to carry a `runtime` export
 * across: a proxy always runs on Node.js. Next refuses route segment config
 * here, so there is no edge/node choice left to make — and no `runtime` line
 * that could quietly stop meaning anything.
 *
 * Everything except the sign-in flow requires a session.
 *
 * This only establishes *who* the caller is. Whether they are an administrator
 * at all, and which capabilities they hold, is decided by the backend against
 * the `Admin_Users` table — a valid Clerk session here means a customer of the
 * water app could reach this middleware and pass it, which is the accepted cost
 * of sharing one Clerk instance. The dashboard layout resolves `/api/admin/me`
 * before rendering anything, and a non-administrator is shown the door there.
 */
/**
 * Sign-**in** only. There is deliberately no `/sign-up` here.
 *
 * Administrators are invited by an existing administrator and bound to a Clerk
 * account on first sign-in. A self-service registration route on the console —
 * even one that leads to a screen this app does not implement — is an invitation
 * to build the path that turns "anybody" into "somebody with a session on the
 * admin origin".
 */
const isPublic = createRouteMatcher(["/sign-in(.*)"]);

export default clerkMiddleware(async (auth, request) => {
  if (!isPublic(request)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next internals and static files, run on everything else.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
