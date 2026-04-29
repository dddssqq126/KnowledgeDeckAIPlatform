"use client";

import { createSimpleStore, createStoreHook } from "./simple-store";

export type AuthUser = { id: number; username: string };

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
};

const STORAGE_KEY = "knowledgedeck-auth";

const authStore = createSimpleStore<AuthState>({
  token: null,
  user: null,
  setSession: (token, user) => authStore.setState({ token, user }),
  clearSession: () => authStore.setState({ token: null, user: null }),
});

export const useAuthStore = createStoreHook(authStore) as ReturnType<typeof createStoreHook<AuthState>> & {
  persist: { rehydrate: () => Promise<void> };
};

function saveAuthState() {
  if (typeof window === "undefined") return;
  const { token, user } = authStore.getState();
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ state: { token, user } }));
}

authStore.subscribe(saveAuthState);

useAuthStore.persist = {
  async rehydrate() {
    if (typeof window === "undefined") return;
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const data = JSON.parse(raw) as { state?: { token?: string | null; user?: AuthUser | null } };
      authStore.setState({
        token: data.state?.token ?? null,
        user: data.state?.user ?? null,
      });
    } catch {
      authStore.setState({ token: null, user: null });
    }
  },
};
