"use client";

import {
  type SlideSession,
  createSlideSession,
  deleteSlideSession,
  listSlideSessions,
  updateSlideSession,
} from "./slides";
import { createSimpleStore, useSimpleStore } from "./simple-store";

type SlideState = {
  sessions: SlideSession[];
  loaded: boolean;
  refresh: () => Promise<void>;
  newSession: () => Promise<SlideSession>;
  remove: (id: number) => Promise<void>;
  rename: (id: number, title: string) => Promise<void>;
  /** Local-only patch (e.g., after a render call updates status/has_pptx). */
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
    slideStore.setState((cur) => ({ sessions: [s, ...cur.sessions] }));
    return s;
  },
  remove: async (id) => {
    await deleteSlideSession(id);
    slideStore.setState((cur) => ({ sessions: cur.sessions.filter((s) => s.id !== id) }));
  },
  rename: async (id, title) => {
    const updated = await updateSlideSession(id, title);
    slideStore.setState((cur) => ({
      sessions: cur.sessions.map((s) =>
        s.id === id ? { ...s, title: updated.title } : s,
      ),
    }));
  },
  patch: (id, patch) => {
    slideStore.setState((cur) => ({
      sessions: cur.sessions.map((s) => (s.id === id ? { ...s, ...patch } : s)),
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

export function useSlideStore<T>(selector: (s: SlideState) => T): T {
  return useSimpleStore(slideStore, selector);
}
