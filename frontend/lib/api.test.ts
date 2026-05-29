import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_API_TIMEOUT_MS, api } from "./api";
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

  it("uses the default API timeout", () => {
    expect(api.defaults.timeout).toBe(DEFAULT_API_TIMEOUT_MS);
  });

  it("attaches Bearer header when a token is set", async () => {
    useAuthStore.getState().setSession("u_7", { id: 7, username: "alice" });
    mock
      .onGet("/echo")
      .reply((config) => [
        200,
        { auth: config.headers?.Authorization ?? null },
      ]);
    const res = await api.get("/echo");
    expect(res.data).toEqual({ auth: "Bearer u_7" });
  });

  it("omits Authorization header when no token is set", async () => {
    mock
      .onGet("/echo")
      .reply((config) => [
        200,
        { auth: config.headers?.Authorization ?? null },
      ]);
    const res = await api.get("/echo");
    expect(res.data).toEqual({ auth: null });
  });

  it("clears session and redirects on 401", async () => {
    useAuthStore.getState().setSession("u_7", { id: 7, username: "alice" });
    mock.onGet("/protected").reply(401, { detail: "invalid_token" });
    const replaceMock = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/dashboard",
      replace: replaceMock,
    });

    await expect(api.get("/protected")).rejects.toThrow();
    expect(useAuthStore.getState().token).toBeNull();
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("does not redirect when already on /login", async () => {
    useAuthStore.getState().setSession("u_7", { id: 7, username: "alice" });
    mock.onPost("/auth/login").reply(401, { detail: "invalid_credentials" });
    const replaceMock = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/login",
      replace: replaceMock,
    });

    await expect(api.post("/auth/login", {})).rejects.toThrow();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("does not clear session when login itself returns 401", async () => {
    // A logged-in user submitting wrong creds on /login should keep their
    // session — the form owns the error display.
    useAuthStore.getState().setSession("u_7", { id: 7, username: "alice" });
    mock.onPost("/auth/login").reply(401, { detail: "invalid_credentials" });
    const replaceMock = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/dashboard",
      replace: replaceMock,
    });

    await expect(api.post("/auth/login", {})).rejects.toThrow();
    expect(useAuthStore.getState().token).toBe("u_7");
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
