"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type AuthUser = { id: number; username: string };

const DEFAULT_EXTERNAL_USERNAME =
  process.env.NEXT_PUBLIC_DEFAULT_USERNAME ?? "external-user";

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
  externalUsername: string;
  setSession: (token: string, user: AuthUser) => void;
  setExternalUser: (username: string, user?: AuthUser | null) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      externalUsername: DEFAULT_EXTERNAL_USERNAME,
      setSession: (token, user) => set({ token, user }),
      setExternalUser: (username, user = null) =>
        set({ externalUsername: username, user, token: null }),
      clearSession: () => set({ token: null, user: null }),
    }),
    {
      name: "knowledgedeck-auth",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);

export function resolveExternalUsername(): string {
  if (typeof window === "undefined") return DEFAULT_EXTERNAL_USERNAME;

  const params = new URLSearchParams(window.location.search);
  const fromQuery =
    params.get("username") ??
    params.get("user_name") ??
    params.get("name") ??
    params.get("user");
  const candidate =
    fromQuery ??
    window.localStorage.getItem("knowledgedeck-external-username") ??
    useAuthStore.getState().externalUsername ??
    DEFAULT_EXTERNAL_USERNAME;
  const username = candidate.trim() || DEFAULT_EXTERNAL_USERNAME;
  window.localStorage.setItem("knowledgedeck-external-username", username);
  return username;
}
