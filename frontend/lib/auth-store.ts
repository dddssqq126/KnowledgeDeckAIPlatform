"use client";

import { createStore, useStoreSelector } from "./simple-store";

export type AuthUser = { id: number; username: string };

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
};

type AuthPersistState = { token: string | null; user: AuthUser | null };

const STORAGE_KEY = "knowledgedeck-auth";

function loadPersisted(): AuthPersistState {
  if (typeof window === "undefined") return { token: null, user: null };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { token: null, user: null };
    const parsed = JSON.parse(raw) as { state?: AuthPersistState };
    return {
      token: parsed.state?.token ?? null,
      user: parsed.state?.user ?? null,
    };
  } catch {
    return { token: null, user: null };
  }
}

function persistState(state: AuthPersistState) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ state }));
}

const persisted = loadPersisted();

const authStore = createStore<AuthState>({
  token: persisted.token,
  user: persisted.user,
  setSession: (token, user) => {
    authStore.setState((prev) => {
      const next = { ...prev, token, user };
      persistState({ token, user });
      return next;
    });
  },
  clearSession: () => {
    authStore.setState((prev) => {
      const next = { ...prev, token: null, user: null };
      persistState({ token: null, user: null });
      return next;
    });
  },
});

type AuthStoreHook = {
  <S>(selector: (state: AuthState) => S): S;
  getState: () => AuthState;
};

export const useAuthStore = ((selector) =>
  useStoreSelector(authStore, selector)) as AuthStoreHook;

useAuthStore.getState = authStore.getState;
