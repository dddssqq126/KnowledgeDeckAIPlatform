"use client";

import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

import { useAuthStore } from "./auth-store";

export const DEFAULT_API_TIMEOUT_MS = 30_000;
// Disable Axios' client-side timeout for endpoints that intentionally wait for
// ingestion/re-indexing. Large PDFs/Office docs can take several minutes to
// parse, chunk, embed, and upsert.
export const LONG_RUNNING_REQUEST_TIMEOUT_MS = 0;

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080",
  timeout: DEFAULT_API_TIMEOUT_MS,
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // 401 on the login endpoint itself is "wrong credentials" — the form
    // owns the error display, so skip the global session-clear + redirect.
    const requestUrl = error.config?.url ?? "";
    const isLoginRequest = requestUrl.endsWith("/auth/login");
    if (error.response?.status === 401 && !isLoginRequest) {
      useAuthStore.getState().clearSession();
      if (
        typeof window !== "undefined" &&
        window.location.pathname !== "/login"
      ) {
        window.location.replace("/login");
      }
    }
    return Promise.reject(error);
  },
);
