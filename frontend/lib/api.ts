"use client";

import axios, { type AxiosError } from "axios";

import { useAuthStore } from "./auth-store";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080",
  timeout: 30_000,
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const requestUrl = error.config?.url ?? "";
    const isLoginRequest = requestUrl.endsWith("/auth/login");
    if (error.response?.status === 401 && !isLoginRequest) {
      useAuthStore.getState().clearSession();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.replace("/login");
      }
    }
    return Promise.reject(error);
  },
);
