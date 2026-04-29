"use client";

import { useSyncExternalStore } from "react";

type Listener = () => void;

export type SimpleStoreApi<T> = {
  getState: () => T;
  setState: (partial: Partial<T> | ((prev: T) => Partial<T>)) => void;
  subscribe: (listener: Listener) => () => void;
};

export function createSimpleStore<T extends object>(initial: T): SimpleStoreApi<T> {
  let state = initial;
  const listeners = new Set<Listener>();

  return {
    getState: () => state,
    setState: (partial) => {
      const nextPatch = typeof partial === "function" ? partial(state) : partial;
      state = { ...state, ...nextPatch };
      listeners.forEach((l) => l());
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export type StoreHook<T extends object> = {
  <R>(selector: (state: T) => R): R;
  (): T;
  getState: () => T;
};

export function createStoreHook<T extends object>(api: SimpleStoreApi<T>): StoreHook<T> {
  const useStore = ((selector?: (state: T) => unknown) => {
    return useSyncExternalStore(
      api.subscribe,
      () => (selector ? selector(api.getState()) : api.getState()),
      () => (selector ? selector(api.getState()) : api.getState()),
    );
  }) as StoreHook<T>;

  useStore.getState = api.getState;
  return useStore;
}
