"use client";

import { createSimpleStore, useSimpleStore } from "./simple-store";

export type AuthUser = { id: number; username: string };

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
};

const STORAGE_KEY = "knowledgedeck-auth";

function loadPersisted(): Pick<AuthState, "token" | "user"> {
  if (typeof window === "undefined") return { token: null, user: null };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { token: null, user: null };
    const parsed = JSON.parse(raw) as { token: string | null; user: AuthUser | null };
    return { token: parsed.token ?? null, user: parsed.user ?? null };
  } catch {
    return { token: null, user: null };
  }
}

const persisted = loadPersisted();
const authStore = createSimpleStore<AuthState>({
  token: persisted.token,
  user: persisted.user,
  setSession: (token, user) => {
    authStore.setState({ token, user });
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user }));
    }
  },
  clearSession: () => {
    authStore.setState({ token: null, user: null });
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  },
});

export function useAuthStore<T>(selector: (s: AuthState) => T): T {
  return useSimpleStore(authStore, selector);
}
