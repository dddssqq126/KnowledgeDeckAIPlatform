"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark";

type ThemeState = {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
};

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: "light",
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set({ theme: get().theme === "dark" ? "light" : "dark" }),
    }),
    {
      name: "knowledgedeck-theme",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);
