import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "./auth-store";

describe("auth store", () => {
  beforeEach(() => {
    useAuthStore.getState().clearSession();
    localStorage.clear();
  });

  it("starts empty", () => {
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("setSession populates user", () => {
    useAuthStore.getState().setSession({ id: 7, username: "alice" });
    expect(useAuthStore.getState().user).toEqual({ id: 7, username: "alice" });
  });

  it("clearSession resets state", () => {
    useAuthStore.getState().setSession({ id: 7, username: "alice" });
    useAuthStore.getState().clearSession();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("persists user to localStorage under knowledgedeck-auth", () => {
    useAuthStore.getState().setSession({ id: 42, username: "carol" });
    const raw = localStorage.getItem("knowledgedeck-auth");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw!).state.user).toEqual({ id: 42, username: "carol" });
  });
});
