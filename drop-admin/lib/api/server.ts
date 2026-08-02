import "server-only";

import { auth } from "@clerk/nextjs/server";

/**
 * The only way this app talks to FastAPI.
 *
 * `server-only` at the top is load-bearing: importing this from a Client
 * Component is a build error rather than a runtime surprise. That matters
 * because the whole point of the module is that the bearer token never reaches
 * the browser — this console renders national ID photographs and M-Pesa
 * numbers, and an XSS on any page of it must not also hand over an admin API
 * token.
 *
 * The token is minted per request by Clerk on the server. The browser only ever
 * holds Clerk's httpOnly session cookie, which is useless against the backend.
 */

const BACKEND = process.env.BACKEND_BASE_URL;

/** A refusal we understood, as opposed to the network falling over. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** `permission_required`, `two_factor_required`, … — branch on this, never on the wording. */
    readonly type?: string,
    readonly permission?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Thrown when the caller is signed in but has no administrator record. */
export class NotAnAdminError extends ApiError {
  constructor(message: string) {
    super(403, message, "not_an_admin");
    this.name = "NotAnAdminError";
  }
}

type Options = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /**
   * Seconds. Omit for no caching, which is the default and the right one for
   * almost everything here — an admin acting on a stale payout queue is worse
   * than an admin waiting 200ms.
   */
  revalidate?: number;
  signal?: AbortSignal;
};

async function parseError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    detail = payload?.detail;
  } catch {
    detail = undefined;
  }

  // FastAPI's `detail` is either a string or, for the typed refusals this
  // platform raises, an object carrying a machine-readable `type`.
  if (detail && typeof detail === "object") {
    const d = detail as { type?: string; message?: string; permission?: string };
    return new ApiError(
      response.status,
      d.message ?? "That request was refused.",
      d.type,
      d.permission,
    );
  }

  if (typeof detail === "string" && detail.trim()) {
    return new ApiError(response.status, detail);
  }

  // Never surface a bare status code to a human. "403" tells an operations
  // manager nothing they can act on.
  return new ApiError(
    response.status,
    response.status >= 500
      ? "The server had a problem. Please try again."
      : "That request could not be completed.",
  );
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  if (!BACKEND) {
    throw new ApiError(500, "BACKEND_BASE_URL is not configured on this server.");
  }

  const { getToken } = await auth();
  const token = await getToken();

  if (!token) {
    // The middleware should have redirected already; this is the belt to its
    // braces, and it must not be reported as a backend failure.
    throw new ApiError(401, "Your session has ended. Please sign in again.");
  }

  const { method = "GET", body, revalidate, signal } = options;

  let response: Response;
  try {
    response = await fetch(`${BACKEND}${path}`, {
      method,
      signal,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      // `no-store` unless a caller opts in. Caching an admin response by
      // accident would show one administrator another's filtered view.
      cache: revalidate === undefined ? "no-store" : undefined,
      next: revalidate === undefined ? undefined : { revalidate },
    });
  } catch (cause) {
    if (cause instanceof Error && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "Could not reach the server. Check your connection.");
  }

  if (response.status === 403) {
    const error = await parseError(response);
    // Distinguish "you are not an administrator" from "you lack this one
    // capability". The first is a wrong door; the second is a real user who
    // needs a different answer.
    if (!error.type) throw new NotAnAdminError(error.message);
    throw error;
  }

  if (!response.ok) throw await parseError(response);

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Convenience wrappers, so call sites read as the verb they are. */
export const get = <T,>(path: string, revalidate?: number) => api<T>(path, { revalidate });
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });
export const put = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body });
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });
