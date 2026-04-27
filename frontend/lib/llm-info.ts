"use client";

import { useEffect } from "react";

import { api } from "./api";
import { mockApi } from "./mock-data";
import { USE_MOCK_DATA } from "./mock-mode";
import { createStore, useStoreSelector } from "./simple-store";

export type LlmInfo = { label: string; model_id: string };

type LlmInfoState = {
  info: LlmInfo | null;
  loaded: boolean;
  refresh: () => Promise<void>;
};

const store = createStore<LlmInfoState>({
  info: null,
  loaded: false,
  async refresh() {
    try {
      if (USE_MOCK_DATA) {
        const info = await mockApi.getLlmInfo();
        store.setState((prev) => ({ ...prev, info, loaded: true }));
        return;
      }
      const res = await api.get<LlmInfo>("/llm/info");
      store.setState((prev) => ({ ...prev, info: res.data, loaded: true }));
    } catch {
      store.setState((prev) => ({ ...prev, loaded: true }));
    }
  },
});

type LlmInfoHook = {
  <S>(selector: (state: LlmInfoState) => S): S;
  getState: () => LlmInfoState;
};

export const useLlmInfoStore = ((selector) => useStoreSelector(store, selector)) as LlmInfoHook;

useLlmInfoStore.getState = store.getState;

export function useLlmInfo(): LlmInfo | null {
  const info = useLlmInfoStore((s) => s.info);
  const loaded = useLlmInfoStore((s) => s.loaded);
  const refresh = useLlmInfoStore((s) => s.refresh);
  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);
  return info;
}
