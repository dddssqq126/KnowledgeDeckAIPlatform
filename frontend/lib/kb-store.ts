"use client";

import { createSimpleStore, createStoreHook } from "./simple-store";
import {
  type KnowledgeBase,
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  updateKnowledgeBase,
} from "./knowledge-bases";

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

const kbStore = createSimpleStore<KbState>({
  kbs: [],
  loaded: false,
  refresh: async () => {
    try {
      kbStore.setState({ kbs: await listKnowledgeBases(), loaded: true });
    } catch {
      kbStore.setState({ loaded: true });
    }
  },
  create: async (name, description) => {
    const created = await createKnowledgeBase({ name, description });
    const row: KnowledgeBase = { ...created, file_count: 0 };
    kbStore.setState((prev) => ({ kbs: [row, ...prev.kbs] }));
    return row;
  },
  remove: async (id) => {
    await deleteKnowledgeBase(id);
    kbStore.setState((prev) => ({ kbs: prev.kbs.filter((k) => k.id !== id) }));
  },
  rename: async (id, name) => {
    const updated = await updateKnowledgeBase(id, { name });
    kbStore.setState((prev) => ({
      kbs: prev.kbs.map((k) =>
        k.id === id ? { ...k, name: updated.name, description: updated.description } : k,
      ),
    }));
  },
  bumpFileCount: (id, delta) => {
    kbStore.setState((prev) => ({
      kbs: prev.kbs.map((k) =>
        k.id === id ? { ...k, file_count: Math.max(0, k.file_count + delta) } : k,
      ),
    }));
  },
  setFileCount: (id, count) => {
    kbStore.setState((prev) => ({
      kbs: prev.kbs.map((k) => (k.id === id ? { ...k, file_count: count } : k)),
    }));
  },
});

export const useKbStore = createStoreHook(kbStore);
