/**
 * The non-hook HTTP client.
 *
 * `useApiRequest` is the right tool everywhere it can be used. A few callers
 * cannot: push-token registration and the image upload helper run outside React
 * and are handed a token.
 *
 * They still need what has nothing to do with React — a timeout, HTTPS
 * enforcement, and an `ApiError` carrying the backend's own `detail` rather than
 * a bare status code. Forty-eight raw `fetch` calls used to throw the
 * transport's own words at the vendor ("Failed to fetch orders"), and several
 * checked `res.ok` and did nothing when it was false.
 *
 * These test the four things it adds over a bare `fetch`, plus the store header
 * this app alone sends.
 */
import { ApiError } from "../errors";
import { apiFetch } from "../apiFetch";

const json = (body: unknown, status = 200) => ({
  status,
  ok: status >= 200 && status < 300,
  json: () => Promise.resolve(body),
});

describe("apiFetch", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    (global as any).__DEV__ = true;
  });

  it("returns the parsed body on success", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(json({ id: "order-1" }));
    await expect(apiFetch("https://api.example.com/orders/1")).resolves.toEqual({
      id: "order-1",
    });
  });

  it("attaches the bearer token when given one", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(json({}));
    await apiFetch("https://api.example.com/me", { token: "jwt-123" });

    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer jwt-123");
  });

  it("sends no Authorization header when there is no session", async () => {
    // The forced-update check runs before anyone has signed in.
    (global.fetch as jest.Mock).mockResolvedValue(json({}));
    await apiFetch("https://api.example.com/app-version");

    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("serialises a JSON body and sets the content type", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(json({}));
    await apiFetch("https://api.example.com/cart", {
      method: "POST",
      body: { product_id: "p1", quantity: 2 },
    });

    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ product_id: "p1", quantity: 2 });
  });

  it("passes FormData through untouched so the platform sets the boundary", async () => {
    // Setting Content-Type by hand on a multipart body omits the boundary and
    // the upload fails server-side with no useful message.
    (global.fetch as jest.Mock).mockResolvedValue(json({ secure_url: "customers/x.webp" }));
    const formData = new FormData();

    await apiFetch("https://api.example.com/upload", { method: "POST", formData });

    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBe(formData);
  });

  it("returns undefined for a 204 rather than trying to parse a body", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ status: 204, ok: true, json: () => Promise.reject(new Error("no body")) });
    await expect(apiFetch("https://api.example.com/push-token", { method: "DELETE" })).resolves.toBeUndefined();
  });

  describe("error normalisation", () => {
    it("throws an ApiError carrying the backend's own sentence", async () => {
      (global.fetch as jest.Mock).mockResolvedValue(
        json({ detail: "Return 2 bottles to place a new order." }, 402),
      );

      await expect(apiFetch("https://api.example.com/cart/quote")).rejects.toMatchObject({
        name: "ApiError",
        status: 402,
        message: "Return 2 bottles to place a new order.",
      });
    });

    it("keeps the machine-readable type so callers need not read prose", async () => {
      (global.fetch as jest.Mock).mockResolvedValue(
        json({ detail: { type: "vendor_conflict", message: "Cart belongs to another store." } }, 409),
      );

      const error = (await apiFetch("https://api.example.com/cart").catch((e) => e)) as ApiError;
      expect(error.type).toBe("vendor_conflict");
    });

    it("survives an error response with no JSON body", async () => {
      // A 502 from a proxy is often HTML. The user still gets a sentence.
      (global.fetch as jest.Mock).mockResolvedValue({
        status: 502,
        ok: false,
        json: () => Promise.reject(new SyntaxError("Unexpected token <")),
      });

      const error = (await apiFetch("https://api.example.com/orders").catch((e) => e)) as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(502);
      expect(error.message).not.toContain("Unexpected token");
    });

    it("reports a dropped connection as reachability, not as a code", async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new TypeError("Network request failed"));

      const error = (await apiFetch("https://api.example.com/orders").catch((e) => e)) as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(0);
      expect(error.message).toMatch(/connection/i);
    });
  });

  describe("HTTPS enforcement", () => {
    it("refuses plaintext HTTP outside development", async () => {
      (global as any).__DEV__ = false;
      await expect(apiFetch("http://api.example.com/orders")).rejects.toBeInstanceOf(ApiError);
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it("allows it in development, where the backend runs on localhost", async () => {
      (global as any).__DEV__ = true;
      (global.fetch as jest.Mock).mockResolvedValue(json({}));
      await expect(apiFetch("http://localhost:8000/orders")).resolves.toBeDefined();
    });
  });

  describe("timeout", () => {
    afterEach(() => jest.useRealTimers());

    it("aborts a request that never completes", async () => {
      // `fetch` has no timeout at all, so without this the caller's `await`
      // simply never returns and the screen spins forever.
      jest.useFakeTimers();
      (global.fetch as jest.Mock).mockImplementation(
        (_url: string, init: any) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener("abort", () => {
              const error: any = new Error("Aborted");
              error.name = "AbortError";
              reject(error);
            });
          }),
      );

      const pending = apiFetch("https://api.example.com/slow").catch((e) => e);
      jest.advanceTimersByTime(200_000);

      const error = (await pending) as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(0);
      expect(error.message).toMatch(/timed out/i);
    });
  });

  describe("store scoping", () => {
    it("sends X-Store-Id when the caller names a store", async () => {
      // A vendor account may own several stores. The backend resolves this
      // against the caller's own stores and 404s on one they do not own, so it
      // selects among granted stores — it never widens access.
      (global.fetch as jest.Mock).mockResolvedValue(json({}));
      await apiFetch("https://api.example.com/vendor/orders", { storeId: "store-2" });

      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(init.headers["X-Store-Id"]).toBe("store-2");
    });

    it("omits the header when no store is named", async () => {
      // `GET /api/vendor/stores` is the one call that must not be scoped — its
      // whole purpose is to return the others.
      (global.fetch as jest.Mock).mockResolvedValue(json({}));
      await apiFetch("https://api.example.com/vendor/stores");

      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(init.headers["X-Store-Id"]).toBeUndefined();
    });

    it("omits the header for an explicitly null store", async () => {
      (global.fetch as jest.Mock).mockResolvedValue(json({}));
      await apiFetch("https://api.example.com/vendor/stores", { storeId: null });

      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(init.headers["X-Store-Id"]).toBeUndefined();
    });
  });

  describe("caller-owned cancellation", () => {
    it("rethrows a caller's abort as-is so a debounced caller can ignore it", async () => {
      // The address autocomplete aborts the in-flight request on every
      // keystroke. That is not a failure to report to the user.
      const controller = new AbortController();
      (global.fetch as jest.Mock).mockImplementation(
        (_url: string, init: any) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener("abort", () => {
              const error: any = new Error("Aborted");
              error.name = "AbortError";
              reject(error);
            });
          }),
      );

      const pending = apiFetch("https://api.example.com/places", { signal: controller.signal }).catch((e) => e);
      controller.abort();

      const error = (await pending) as Error;
      expect(error).not.toBeInstanceOf(ApiError);
      expect(error.name).toBe("AbortError");
    });

    it("does not issue a request that was already cancelled", async () => {
      const controller = new AbortController();
      controller.abort();
      (global.fetch as jest.Mock).mockImplementation(
        (_url: string, init: any) =>
          init.signal.aborted
            ? Promise.reject(Object.assign(new Error("Aborted"), { name: "AbortError" }))
            : Promise.resolve(json({})),
      );

      await expect(
        apiFetch("https://api.example.com/places", { signal: controller.signal }),
      ).rejects.toMatchObject({ name: "AbortError" });
    });
  });
});
