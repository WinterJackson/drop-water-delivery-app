/**
 * Non-hook counterpart to `useApiRequest`.
 *
 * `useApiRequest` is the right tool everywhere it can be used, and every screen
 * and query hook uses it. Three callers cannot: the Zustand availability store,
 * the offline replay queue, and the background location task all run outside
 * React and are handed a token rather than obtaining one.
 *
 * They still need the parts that had nothing to do with React — a timeout,
 * HTTPS enforcement, and an `ApiError` carrying the backend's own `detail`
 * instead of a bare status code. What they deliberately do *not* get is the
 * 401 sign-out: none of them is on screen, and signing a rider out from a
 * background flush would drop them mid-delivery with no explanation. They
 * surface the error to their caller, and the next foreground request signs out
 * if the session really is gone.
 */
import { ApiError, toApiError } from "./errors";
import { kindForMethod, timeoutFor, type RequestKind } from "./netBudget";

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  token?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
  /**
   * Override the budget. Leave it unset: `netBudget` picks one from the
   * connection and the method, which is right far more often than a number
   * written at a call site can be.
   */
  timeoutMs?: number;
  /**
   * `upload` where the body is a photograph. Aborting one at 90% and
   * restarting is strictly worse than waiting — and it happens at a
   * customer's gate, with the job unable to finish.
   */
  kind?: RequestKind;
  /** Pass a `FormData` through untouched, letting the platform set the boundary. */
  formData?: FormData;
  /**
   * Caller-owned cancellation, on top of the timeout — a debounced autocomplete
   * aborts the in-flight request on every keystroke.
   */
  signal?: AbortSignal;
}

export async function apiFetch<T = unknown>(
  url: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const {
    method = "GET",
    token,
    body,
    headers = {},
    formData,
    signal,
    kind,
  } = options;

  // Method decides the kind unless the caller knows better; `formData` is
  // always an upload, because in these apps it only ever carries an image.
  const requestKind: RequestKind = kind ?? (formData ? "upload" : kindForMethod(method));
  const timeoutMs = options.timeoutMs ?? timeoutFor(requestKind);

  if (!__DEV__ && url.startsWith("http://")) {
    throw new ApiError(
      "Security Exception: Insecure HTTP connection blocked in non-development mode.",
      0
    );
  }

  // `fetch` has no timeout at all, so a request that never completes never
  // rejects — the caller's `await` simply never returns.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // The caller's abort has to reach the same controller, or cancelling would
  // only ever stop the timeout and never the request.
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort);
  if (signal?.aborted) controller.abort();

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      signal: controller.signal,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(formData ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
    });
  } catch (e: any) {
    // A caller-initiated abort is not a failure to report — rethrow it as-is so
    // a debounced caller can recognise and ignore it.
    if (signal?.aborted) throw e;
    throw new ApiError(
      e?.name === "AbortError"
        ? "The request timed out. Please try again."
        : "We couldn't reach the server. Check your connection and try again.",
      0
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }

  if (res.status === 204) return undefined as T;

  const payload = await res.json().catch(() => null);
  if (!res.ok) throw toApiError(res.status, payload);
  return payload as T;
}
