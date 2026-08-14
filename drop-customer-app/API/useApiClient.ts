import { useAuth } from "@clerk/clerk-expo";
import axios, { AxiosError, AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { useCallback, useMemo } from "react";

import { ApiError, toApiError } from "./errors";
import { kindForMethod, timeoutFor } from "./netBudget";

/**
 * Centralised HTTP client.
 *
 * Handles the three things every backend call needs and that the raw `fetch`
 * calls scattered through the hooks were each doing differently (or not at all):
 *   1. injects the Clerk JWT,
 *   2. signs the user out on a 401 instead of failing silently,
 *   3. converts every failure into an `ApiError` whose message is the backend's
 *      own `detail`, so callers can show it verbatim.
 */
export const useApiClient = () => {
    const { getToken, signOut } = useAuth();

    const apiClient = useMemo(() => {
        const client = axios.create({
            headers: {
                "Content-Type": "application/json",
            },
        });

        // The timeout is per request, not per client.
        //
        // It was a flat 15 s, which is a broadband number. On a congested 3G cell
        // a request that would have completed at 25 s was aborted, retried twice,
        // and reported as a failure — three quarters of a minute of spinner and
        // three uploads of the same body over metered data, manufacturing exactly
        // the hang the timeout existed to prevent. `netBudget` reads the live
        // connection and the request kind instead. See `API/netBudget.ts`.
        client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
            if (config.timeout === undefined || config.timeout === 0) {
                const kind = config.data instanceof FormData ? "upload" : kindForMethod(config.method?.toUpperCase());
                config.timeout = timeoutFor(kind);
            }
            return config;
        });

        // Inject Clerk Auth Token strictly onto non-public routes
        client.interceptors.request.use(
            async (config: InternalAxiosRequestConfig) => {
                // strict HTTPS enforcement in production
                if (!__DEV__ && config.url?.startsWith("http://")) {
                    return Promise.reject(
                        new ApiError(
                            "Security Exception: Insecure HTTP connection blocked in non-development mode.",
                            0
                        )
                    );
                }

                try {
                    const token = await getToken();
                    if (token) {
                        config.headers.Authorization = `Bearer ${token}`;
                    }
                    return config;
                } catch (error) {
                    if (__DEV__) console.error("Token interception failed", error);
                    return config;
                }
            },
            (error: AxiosError) => Promise.reject(error)
        );

        // Standardised Error Interceptor
        client.interceptors.response.use(
            (response: AxiosResponse) => response,
            async (error: AxiosError) => {
                if (error instanceof ApiError) return Promise.reject(error);

                const status = error.response?.status ?? 0;

                if (status === 401) {
                    // Force session wipe upon compromised or expired security JWT
                    if (__DEV__) console.warn("401 Unauthorized captured - signing out client");
                    try {
                        await signOut();
                    } catch (signOutError) {
                        if (__DEV__) console.error("Sign-out after 401 failed", signOutError);
                    }
                }

                const apiError = toApiError(
                    status,
                    error.response?.data,
                    status === 0
                        ? error.code === "ECONNABORTED"
                            ? "The request timed out. Please try again."
                            : undefined
                        : undefined
                );

                if (__DEV__) {
                    console.error(
                        `API ${error.config?.method?.toUpperCase() ?? "?"} ${error.config?.url ?? "?"} → ${status}: ${apiError.message}`
                    );
                }

                return Promise.reject(apiError);
            }
        );

        return client;
    }, [getToken, signOut]);

    return apiClient;
};

/**
 * Thin request helpers over `useApiClient`, returning parsed data directly.
 *
 * Query hooks use these so that token injection, 401 handling and error
 * normalisation are impossible to forget — which is exactly what happened when
 * each hook hand-rolled its own `fetch`.
 */
export const useApiRequest = () => {
    const client = useApiClient();

    const request = useCallback(
        async <T = unknown>(config: AxiosRequestConfig): Promise<T> => {
            const response = await client.request<T>(config);
            return response.data;
        },
        [client]
    );

    const get = useCallback(
        <T = unknown>(url: string, config?: AxiosRequestConfig) =>
            request<T>({ ...config, url, method: "GET" }),
        [request]
    );

    const post = useCallback(
        <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
            request<T>({ ...config, url, method: "POST", data }),
        [request]
    );

    const put = useCallback(
        <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
            request<T>({ ...config, url, method: "PUT", data }),
        [request]
    );

    const patch = useCallback(
        <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
            request<T>({ ...config, url, method: "PATCH", data }),
        [request]
    );

    const del = useCallback(
        <T = unknown>(url: string, config?: AxiosRequestConfig) =>
            request<T>({ ...config, url, method: "DELETE" }),
        [request]
    );

    return useMemo(() => ({ request, get, post, put, patch, del }), [request, get, post, put, patch, del]);
};

export default useApiClient;
