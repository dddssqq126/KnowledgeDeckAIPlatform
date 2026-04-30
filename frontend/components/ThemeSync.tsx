"use client";

import { useEffect } from "react";

import { useThemeStore } from "../lib/theme-store";

export function ThemeSync() {
  const mode = useThemeStore((s) => s.mode);

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.body.dataset.theme = mode;
  }, [mode]);

  return null;
}
