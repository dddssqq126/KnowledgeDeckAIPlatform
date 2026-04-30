"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type ThemeMode = "dark" | "light";

type ThemeState = {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
};

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: "dark",
      setMode: (mode) => set({ mode }),
      toggle: () => set({ mode: get().mode === "dark" ? "light" : "dark" }),
    }),
    {
      name: "knowledgedeck-theme",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);
