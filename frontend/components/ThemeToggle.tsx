"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type ThemeMode = "light" | "dark";

const STORAGE_KEY = "knowledgedeck-theme";

function applyTheme(mode: ThemeMode) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", mode === "dark");
}

export function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>("light");

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    const next: ThemeMode = saved === "dark" ? "dark" : "light";
    setMode(next);
    applyTheme(next);
  }, []);

  function toggle() {
    const next: ThemeMode = mode === "dark" ? "light" : "dark";
    setMode(next);
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="flex w-full items-center gap-2 rounded-md px-2 py-1 hover:bg-muted hover:text-foreground"
      aria-label="Toggle dark mode"
      title="切換黑暗模式"
    >
      {mode === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      {mode === "dark" ? "Light Mode" : "Dark Mode"}
    </button>
  );
}
