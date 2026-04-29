"use client";

import { createSimpleStore, createStoreHook } from "./simple-store";
import {
  type SlideSession,
  createSlideSession,
  deleteSlideSession,
  listSlideSessions,
  updateSlideSession,
} from "./slides";

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

const slideStore = createSimpleStore<SlideState>({
  sessions: [],
  loaded: false,
  refresh: async () => {
    try {
      slideStore.setState({ sessions: await listSlideSessions(), loaded: true });
    } catch {
      slideStore.setState({ loaded: true });
    }
  },
  newSession: async () => {
    const s = await createSlideSession();
    slideStore.setState((prev) => ({ sessions: [s, ...prev.sessions] }));
    return s;
  },
  remove: async (id) => {
    await deleteSlideSession(id);
    slideStore.setState((prev) => ({ sessions: prev.sessions.filter((s) => s.id !== id) }));
  },
  rename: async (id, title) => {
    const updated = await updateSlideSession(id, title);
    slideStore.setState((prev) => ({
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, title: updated.title } : s)),
    }));
  },
  patch: (id, patch) => {
    slideStore.setState((prev) => ({
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    }));
  },
  bumpUpdatedAt: (id) => {
    const now = new Date().toISOString();
    const list = [...slideStore.getState().sessions];
    const idx = list.findIndex((s) => s.id === id);
    if (idx < 0) return;
    const [target] = list.splice(idx, 1);
    list.unshift({ ...target, updated_at: now });
    slideStore.setState({ sessions: list });
  },
});

export const useSlideStore = createStoreHook(slideStore);
