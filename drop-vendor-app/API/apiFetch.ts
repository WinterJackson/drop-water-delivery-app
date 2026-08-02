/**
 * Non-hook counterpart to `useApiRequest`.
 *
 * `useApiRequest` is the right tool everywhere it can be used, and every screen
 * and query hook uses it. A few callers cannot: the push-token registration and
 * the image upload helper run outside React and are handed a token rather than
 * obtaining one.
 *
 * They still need the parts that had nothing to do with React — a timeout,
 * HTTPS enforcement, and an `ApiError` carrying the backend's own `detail`
 * instead of a bare status code. What they deliberately do *not* get is the
 * 401 sign-out: none of them is driving a screen, and a background failure
 * should not tear down the session under whatever the vendor is doing. They
 * surface the error to their caller, and the next foreground request signs out
 * if the session really is gone.
 */
import { ApiError, toApiError } from "./errors";

/** Same budget as `useApiRequest`. */
const DEFAULT_TIMEOUT_MS = 15_000;

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  token?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
  timeoutMs?: number;
  /** Pass a `FormData` through untouched, letting the platform set the boundary. */
  formData?: FormData;
  /**
   * Caller-owned cancellation, on top of the timeout — a debounced autocomplete
   * aborts the in-flight request on every keystroke.
   */
  signal?: AbortSignal;
  /**
   * The store this request acts on. A vendor account may own several; the
   * backend resolves `X-Store-Id` against the caller's own stores and 404s on
   * one they do not own, so this selects among granted stores — it never
   * widens access.
   */
  storeId?: string | null;
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
    timeoutMs = DEFAULT_TIMEOUT_MS,
    formData,
    signal,
    storeId,
  } = options;

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
        ...(storeId ? { "X-Store-Id": storeId } : {}),
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
