"use client";

import { useEffect } from "react";

import { api } from "./api";
import { createSimpleStore, createStoreHook } from "./simple-store";

export type LlmInfo = { label: string; model_id: string };

type LlmInfoState = {
  info: LlmInfo | null;
  loaded: boolean;
  refresh: () => Promise<void>;
};

const llmInfoStore = createSimpleStore<LlmInfoState>({
  info: null,
  loaded: false,
  async refresh() {
    try {
      const res = await api.get<LlmInfo>("/llm/info");
      llmInfoStore.setState({ info: res.data, loaded: true });
    } catch {
      llmInfoStore.setState({ loaded: true });
    }
  },
});

export const useLlmInfoStore = createStoreHook(llmInfoStore);

export function useLlmInfo(): LlmInfo | null {
  const info = useLlmInfoStore((s) => s.info);
  const loaded = useLlmInfoStore((s) => s.loaded);
  const refresh = useLlmInfoStore((s) => s.refresh);
  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);
  return info;
}
