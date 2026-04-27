"use client";

import {
  type ChatSession,
  createSession,
  deleteSession,
  listSessions,
  updateSession,
} from "./chat";
import { createStore, useStoreSelector } from "./simple-store";

type ChatSessionsState = {
  sessions: ChatSession[];
  loaded: boolean;
  refresh: () => Promise<void>;
  newChat: () => Promise<ChatSession>;
  remove: (id: number) => Promise<void>;
  rename: (id: number, title: string) => Promise<ChatSession>;
  bumpUpdatedAt: (id: number) => void;
};

const store = createStore<ChatSessionsState>({
  sessions: [],
  loaded: false,
  refresh: async () => {
    try {
      const sessions = await listSessions();
      store.setState((prev) => ({ ...prev, sessions, loaded: true }));
    } catch {
      store.setState((prev) => ({ ...prev, loaded: true }));
    }
  },
  newChat: async () => {
    const s = await createSession();
    store.setState((prev) => ({ ...prev, sessions: [s, ...prev.sessions] }));
    return s;
  },
  remove: async (id) => {
    await deleteSession(id);
    store.setState((prev) => ({ ...prev, sessions: prev.sessions.filter((s) => s.id !== id) }));
  },
  rename: async (id, title) => {
    const updated = await updateSession(id, title);
    store.setState((prev) => ({
      ...prev,
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, title: updated.title } : s)),
    }));
    return updated;
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

type ChatStoreHook = {
  <S>(selector: (state: ChatSessionsState) => S): S;
  getState: () => ChatSessionsState;
};

export const useChatSessionsStore = ((selector) =>
  useStoreSelector(store, selector)) as ChatStoreHook;

useChatSessionsStore.getState = store.getState;
