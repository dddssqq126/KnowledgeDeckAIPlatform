"use client";

import { useEffect } from "react";

import { api } from "./api";
import { createSimpleStore, useSimpleStore } from "./simple-store";

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
      // Auth-gated endpoint; on 401 the api layer redirects to /login.
      // Any other failure leaves the label hidden — the rest of the page
      // works fine without it.
      llmInfoStore.setState({ loaded: true });
    }
  },
});

export function useLlmInfoStore<TSlice>(selector: (s: LlmInfoState) => TSlice): TSlice {
  return useSimpleStore(llmInfoStore, selector);
}

/** Hydrates the store on first call. Safe to call from multiple components —
 * subsequent calls no-op once `loaded` is true. */
export function useLlmInfo(): LlmInfo | null {
  const info = useLlmInfoStore((s) => s.info);
  const loaded = useLlmInfoStore((s) => s.loaded);
  const refresh = useLlmInfoStore((s) => s.refresh);
  useEffect(() => {
    if (!loaded) void refresh();
  }, [loaded, refresh]);
  return info;
}
