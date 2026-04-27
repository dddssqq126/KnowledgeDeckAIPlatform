"use client";

import {
  type SlideSession,
  createSlideSession,
  deleteSlideSession,
  listSlideSessions,
  updateSlideSession,
} from "./slides";
import { createStore, useStoreSelector } from "./simple-store";

type SlideState = {
  sessions: SlideSession[];
  loaded: boolean;
  refresh: () => Promise<void>;
  newSession: () => Promise<SlideSession>;
  remove: (id: number) => Promise<void>;
  rename: (id: number, title: string) => Promise<void>;
  patch: (id: number, patch: Partial<SlideSession>) => void;
  bumpUpdatedAt: (id: number) => void;
};

const store = createStore<SlideState>({
  sessions: [],
  loaded: false,
  refresh: async () => {
    try {
      const sessions = await listSlideSessions();
      store.setState((prev) => ({ ...prev, sessions, loaded: true }));
    } catch {
      store.setState((prev) => ({ ...prev, loaded: true }));
    }
  },
  newSession: async () => {
    const s = await createSlideSession();
    store.setState((prev) => ({ ...prev, sessions: [s, ...prev.sessions] }));
    return s;
  },
  remove: async (id) => {
    await deleteSlideSession(id);
    store.setState((prev) => ({ ...prev, sessions: prev.sessions.filter((s) => s.id !== id) }));
  },
  rename: async (id, title) => {
    const updated = await updateSlideSession(id, title);
    store.setState((prev) => ({
      ...prev,
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, title: updated.title } : s)),
    }));
  },
  patch: (id, patch) => {
    store.setState((prev) => ({
      ...prev,
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    }));
  },
  bumpUpdatedAt: (id) => {
    const now = new Date().toISOString();
    store.setState((prev) => {
      const list = [...prev.sessions];
      const idx = list.findIndex((s) => s.id === id);
      if (idx < 0) return prev;
      const [target] = list.splice(idx, 1);
      list.unshift({ ...target, updated_at: now });
      return { ...prev, sessions: list };
    });
  },
});

type SlideStoreHook = {
  <S>(selector: (state: SlideState) => S): S;
  getState: () => SlideState;
};

export const useSlideStore = ((selector) => useStoreSelector(store, selector)) as SlideStoreHook;

useSlideStore.getState = store.getState;
