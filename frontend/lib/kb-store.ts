"use client";

import {
  type KnowledgeBase,
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  updateKnowledgeBase,
} from "./knowledge-bases";
import { createStore, useStoreSelector } from "./simple-store";

type KbState = {
  kbs: KnowledgeBase[];
  loaded: boolean;
  refresh: () => Promise<void>;
  create: (name: string, description?: string | null) => Promise<KnowledgeBase>;
  remove: (id: number) => Promise<void>;
  rename: (id: number, name: string) => Promise<void>;
  bumpFileCount: (id: number, delta: number) => void;
  setFileCount: (id: number, count: number) => void;
};

const store = createStore<KbState>({
  kbs: [],
  loaded: false,
  refresh: async () => {
    try {
      const kbs = await listKnowledgeBases();
      store.setState((prev) => ({ ...prev, kbs, loaded: true }));
    } catch {
      store.setState((prev) => ({ ...prev, loaded: true }));
    }
  },
  create: async (name, description) => {
    const created = await createKnowledgeBase({ name, description });
    const row: KnowledgeBase = {
      id: created.id,
      name: created.name,
      description: created.description,
      file_count: 0,
      created_at: created.created_at,
    };
    store.setState((prev) => ({ ...prev, kbs: [row, ...prev.kbs] }));
    return row;
  },
  remove: async (id) => {
    await deleteKnowledgeBase(id);
    store.setState((prev) => ({ ...prev, kbs: prev.kbs.filter((k) => k.id !== id) }));
  },
  rename: async (id, name) => {
    const updated = await updateKnowledgeBase(id, { name });
    store.setState((prev) => ({
      ...prev,
      kbs: prev.kbs.map((k) =>
        k.id === id ? { ...k, name: updated.name, description: updated.description } : k,
      ),
    }));
  },
  bumpFileCount: (id, delta) => {
    store.setState((prev) => ({
      ...prev,
      kbs: prev.kbs.map((k) =>
        k.id === id ? { ...k, file_count: Math.max(0, k.file_count + delta) } : k,
      ),
    }));
  },
  setFileCount: (id, count) => {
    store.setState((prev) => ({
      ...prev,
      kbs: prev.kbs.map((k) => (k.id === id ? { ...k, file_count: count } : k)),
    }));
  },
});

type KbStoreHook = {
  <S>(selector: (state: KbState) => S): S;
  getState: () => KbState;
};

export const useKbStore = ((selector) => useStoreSelector(store, selector)) as KbStoreHook;

useKbStore.getState = store.getState;
