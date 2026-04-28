import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { useAuthStore } from "./auth-store";

describe("api axios instance", () => {
  let mock: MockAdapter;

  beforeEach(() => {
    mock = new MockAdapter(api);
    useAuthStore.getState().clearSession();
    localStorage.clear();
  });

  afterEach(() => {
    mock.restore();
    vi.unstubAllGlobals();
  });

  it("does not attach Authorization header", async () => {
    useAuthStore.getState().setSession({ id: 7, username: "alice" });
    mock.onGet("/echo").reply((config) => [200, { auth: config.headers?.Authorization ?? null }]);
    const res = await api.get("/echo");
    expect(res.data).toEqual({ auth: null });
  });

  it("clears session and redirects on 401", async () => {
    useAuthStore.getState().setSession({ id: 7, username: "alice" });
    mock.onGet("/protected").reply(401, { detail: "invalid_user" });
    const replaceMock = vi.fn();
    vi.stubGlobal("location", { ...window.location, pathname: "/dashboard", replace: replaceMock });

    await expect(api.get("/protected")).rejects.toThrow();
    expect(useAuthStore.getState().user).toBeNull();
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("does not clear session when login itself returns 401", async () => {
    useAuthStore.getState().setSession({ id: 7, username: "alice" });
    mock.onPost("/auth/login").reply(401, { detail: "invalid_credentials" });
    const replaceMock = vi.fn();
    vi.stubGlobal("location", { ...window.location, pathname: "/dashboard", replace: replaceMock });

    await expect(api.post("/auth/login", {})).rejects.toThrow();
    expect(useAuthStore.getState().user).toEqual({ id: 7, username: "alice" });
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
