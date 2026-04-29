"use client";

import {
  type ChatSession,
  createSession,
  deleteSession,
  listSessions,
  updateSession,
} from "./chat";
import { createSimpleStore, useSimpleStore } from "./simple-store";

type ChatSessionsState = {
  sessions: ChatSession[];
  loaded: boolean;
  refresh: () => Promise<void>;
  newChat: () => Promise<ChatSession>;
  remove: (id: number) => Promise<void>;
  rename: (id: number, title: string) => Promise<ChatSession>;
  // Local-only update (e.g., after sending a message we already know the
  // server side has touched updated_at). Keeps the sidebar in sync without
  // an extra round-trip.
  bumpUpdatedAt: (id: number) => void;
};

const chatStore = createSimpleStore<ChatSessionsState>({
  sessions: [],
  loaded: false,
  refresh: async () => {
    try {
      chatStore.setState({ sessions: await listSessions(), loaded: true });
    } catch {
      chatStore.setState({ loaded: true });
    }
  },
  newChat: async () => {
    const s = await createSession();
    chatStore.setState((cur) => ({ sessions: [s, ...cur.sessions] }));
    return s;
  },
  remove: async (id) => {
    await deleteSession(id);
    chatStore.setState((cur) => ({ sessions: cur.sessions.filter((s) => s.id !== id) }));
  },
  rename: async (id, title) => {
    const updated = await updateSession(id, title);
    chatStore.setState((cur) => ({
      sessions: cur.sessions.map((s) =>
        s.id === id ? { ...s, title: updated.title } : s,
      ),
    }));
    return updated;
  },
  bumpUpdatedAt: (id) => {
    const now = new Date().toISOString();
    const list = [...chatStore.getState().sessions];
    const idx = list.findIndex((s) => s.id === id);
    if (idx < 0) return;
    const [target] = list.splice(idx, 1);
    list.unshift({ ...target, updated_at: now });
    chatStore.setState({ sessions: list });
  },
});

export function useChatSessionsStore<T>(selector: (s: ChatSessionsState) => T): T {
  return useSimpleStore(chatStore, selector);
}
