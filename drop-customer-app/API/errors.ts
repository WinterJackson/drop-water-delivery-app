/**
 * Normalised API errors.
 *
 * The app's own guide says to show users the backend's message and never to
 * surface raw HTTP status codes — but almost every query hook was throwing
 * `new Error("Network error")` or `` `Orders fetch failed: ${res.status}` ``,
 * discarding the `detail` FastAPI had carefully written. So a customer blocked by
 * an outstanding bottle deposit (402), a locked cart (409), or an out-of-range
 * address (400) saw the same meaningless "Network error" toast in every case.
 *
 * Everything that talks to the backend now throws an `ApiError` whose `message`
 * is already presentable, so callers can pass it straight to `Toast.error`.
 */

export class ApiError extends Error {
	readonly status: number;
	/** Raw `detail` payload, for the rare caller that needs to branch on shape. */
	readonly detail: unknown;
	/** Backend-provided machine-readable discriminator, when there is one. */
	readonly type?: string;

	constructor(message: string, status: number, detail?: unknown, type?: string) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.detail = detail;
		this.type = type;
	}

	/** Transport failure — no response ever arrived. */
	get isNetworkError() {
		return this.status === 0;
	}

	get isAuthError() {
		return this.status === 401 || this.status === 403;
	}
}

const FALLBACK_BY_STATUS: Record<number, string> = {
	0: "We couldn't reach the server. Check your connection and try again.",
	400: "That request couldn't be completed. Please review the details and try again.",
	401: "Your session has expired. Please sign in again.",
	402: "There's an outstanding balance on your account.",
	403: "You don't have permission to do that.",
	404: "We couldn't find what you were looking for.",
	409: "That conflicts with something already in progress. Please refresh and try again.",
	422: "Some of the details provided weren't valid.",
	429: "Too many attempts. Please wait a moment and try again.",
	500: "Something went wrong on our side. Please try again shortly.",
	502: "The payment service is unavailable right now. Please try again shortly.",
	503: "The service is temporarily unavailable. Please try again shortly.",
};

/**
 * Pull a human-readable message out of whatever the backend returned.
 *
 * FastAPI's `detail` is a string for `HTTPException`, an array of field errors for
 * a 422, and occasionally a nested object (the cart's `vendor_conflict`).
 */
export function extractDetailMessage(detail: unknown): string | null {
	if (!detail) return null;

	if (typeof detail === "string") return detail;

	if (Array.isArray(detail)) {
		// 422 validation errors: [{ loc, msg, type }, ...]
		const messages = detail
			.map((entry: any) => (typeof entry === "string" ? entry : entry?.msg))
			.filter(Boolean);
		return messages.length ? messages.join(". ") : null;
	}

	if (typeof detail === "object") {
		const obj = detail as Record<string, unknown>;
		for (const key of ["message", "detail", "error", "msg"]) {
			const value = obj[key];
			if (typeof value === "string" && value) return value;
		}
	}

	return null;
}

/** Build an ApiError from a raw response body and status. */
export function toApiError(status: number, body: unknown, fallback?: string): ApiError {
	const detail = (body as any)?.detail ?? body;
	const message =
		extractDetailMessage(detail) ??
		fallback ??
		FALLBACK_BY_STATUS[status] ??
		"Something went wrong. Please try again.";
	const type =
		detail && typeof detail === "object" && typeof (detail as any).type === "string"
			? (detail as any).type
			: undefined;
	return new ApiError(message, status, detail, type);
}

/**
 * React Query `retry` predicate.
 *
 * Retrying a 4xx never helps — the request was refused, not dropped. Worse, the
 * 401 handler in `useApiClient` signs the user out, so a plain `retry: 2` fired
 * three sign-outs for one expired session, and a 400 or 404 took three
 * round-trips to reach the user. Retry transport failures and 5xx only.
 *
 * Pass to any hook that needs a different attempt budget:
 * `retry: retryTransientOnly(1)`.
 */
export function retryTransientOnly(maxAttempts = 2) {
	return (failureCount: number, error: unknown) => {
		const status = error instanceof ApiError ? error.status : (error as any)?.status ?? 0;
		if (status >= 400 && status < 500) return false;
		return failureCount < maxAttempts;
	};
}

/**
 * Safe message for any thrown value — use this at the UI boundary so a Toast can
 * never render "[object Object]" or an empty string.
 */
export function errorMessage(error: unknown, fallback = "Something went wrong. Please try again."): string {
	if (error instanceof ApiError) return error.message;
	if (error instanceof Error && error.message) return error.message;
	const fromDetail = extractDetailMessage(error);
	return fromDetail ?? fallback;
}
