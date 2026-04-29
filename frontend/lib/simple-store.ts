"use client";

import { useSyncExternalStore } from "react";

type Listener = () => void;

export type StoreApi<T> = {
  getState: () => T;
  setState: (updater: Partial<T> | ((prev: T) => Partial<T>)) => void;
  subscribe: (listener: Listener) => () => void;
};

export function createSimpleStore<T extends object>(initial: T): StoreApi<T> {
  let state = initial;
  const listeners = new Set<Listener>();

  return {
    getState: () => state,
    setState: (updater) => {
      const patch = typeof updater === "function" ? updater(state) : updater;
      state = { ...state, ...patch };
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useSimpleStore<TState, TSlice>(
  store: StoreApi<TState>,
  selector: (s: TState) => TSlice,
): TSlice {
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.getState()),
    () => selector(store.getState()),
  );
}
