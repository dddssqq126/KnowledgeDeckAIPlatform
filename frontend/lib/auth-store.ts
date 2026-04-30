"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { AUTO_LOGIN } from "./runtime-config";

export type AuthUser = { id: number; username: string };

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: AUTO_LOGIN ? "mock-token" : null,
      user: AUTO_LOGIN ? { id: 1, username: "mock-user" } : null,
      setSession: (token, user) => set({ token, user }),
      clearSession: () => set({ token: null, user: null }),
    }),
    {
      name: "knowledgedeck-auth",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);
