"use client";

import { createStore, useStoreSelector } from "./simple-store";

export type AuthUser = { id: number; username: string };

export type AuthState = {
  user: AuthUser | null;
  setSession: (user: AuthUser) => void;
  clearSession: () => void;
};

type AuthPersistState = { user: AuthUser | null };

const STORAGE_KEY = "knowledgedeck-auth";

function loadPersisted(): AuthPersistState {
  if (typeof window === "undefined") return { user: null };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { user: null };
    const parsed = JSON.parse(raw) as { state?: AuthPersistState };
    return {
      user: parsed.state?.user ?? null,
    };
  } catch {
    return { user: null };
  }
}

function persistState(state: AuthPersistState) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ state }));
}

const persisted = loadPersisted();

const authStore = createStore<AuthState>({
  user: persisted.user,
  setSession: (user) => {
    authStore.setState((prev) => {
      const next = { ...prev, user };
      persistState({ user });
      return next;
    });
  },
  clearSession: () => {
    authStore.setState((prev) => {
      const next = { ...prev, user: null };
      persistState({ user: null });
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
