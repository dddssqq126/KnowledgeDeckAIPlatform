import { beforeEach, describe, expect, it } from "vitest";

import { useThemeStore } from "./theme-store";

describe("theme store", () => {
  beforeEach(() => {
    localStorage.clear();
    useThemeStore.getState().setTheme("light");
  });

  it("defaults to light", () => {
    expect(useThemeStore.getState().theme).toBe("light");
  });

  it("toggles and persists dark mode", () => {
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe("dark");
    const raw = localStorage.getItem("knowledgedeck-theme");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw!).state.theme).toBe("dark");
  });
});
