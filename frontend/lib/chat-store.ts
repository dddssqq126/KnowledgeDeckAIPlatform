"use client";

import { createSimpleStore, createStoreHook } from "./simple-store";
import {
  type ChatSession,
  createSession,
  deleteSession,
  listSessions,
  updateSession,
} from "./chat";

type ChatSessionsState = {
  sessions: ChatSession[];
  loaded: boolean;
  refresh: () => Promise<void>;
  newChat: () => Promise<ChatSession>;
  remove: (id: number) => Promise<void>;
  rename: (id: number, title: string) => Promise<ChatSession>;
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
    chatStore.setState((prev) => ({ sessions: [s, ...prev.sessions] }));
    return s;
  },
  remove: async (id) => {
    await deleteSession(id);
    chatStore.setState((prev) => ({ sessions: prev.sessions.filter((s) => s.id !== id) }));
  },
  rename: async (id, title) => {
    const updated = await updateSession(id, title);
    chatStore.setState((prev) => ({
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, title: updated.title } : s)),
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

export const useChatSessionsStore = createStoreHook(chatStore);
