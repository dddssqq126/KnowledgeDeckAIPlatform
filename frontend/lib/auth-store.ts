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
const DEFAULT_TOKEN = process.env.NEXT_PUBLIC_DEFAULT_TOKEN ?? "dev-token";
const DEFAULT_OWNER_USER_ID = Number(process.env.NEXT_PUBLIC_DEFAULT_OWNER_USER_ID ?? "1");
const DEFAULT_USERNAME = process.env.NEXT_PUBLIC_DEFAULT_USERNAME ?? "owner";

const defaultUser: AuthUser = {
  id: Number.isFinite(DEFAULT_OWNER_USER_ID) ? DEFAULT_OWNER_USER_ID : 1,
  username: DEFAULT_USERNAME,
};

function defaultAuthState() {
  return { token: DEFAULT_TOKEN, user: defaultUser };
}

const authStore = createSimpleStore<AuthState>({
  ...defaultAuthState(),
  setSession: (token, user) => authStore.setState({ token, user }),
  clearSession: () => authStore.setState(defaultAuthState()),
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
    if (!raw) {
      authStore.setState(defaultAuthState());
      return;
    }
    try {
      const data = JSON.parse(raw) as { state?: { token?: string | null; user?: AuthUser | null } };
      authStore.setState({
        token: data.state?.token ?? DEFAULT_TOKEN,
        user: data.state?.user ?? defaultUser,
      });
    } catch {
      authStore.setState(defaultAuthState());
    }
  },
};
