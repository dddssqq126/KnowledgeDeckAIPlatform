import { render, screen, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "./AuthGuard";
import { api } from "../lib/api";
import { useAuthStore } from "../lib/auth-store";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: replaceMock }),
}));

describe("AuthGuard", () => {
  let mock: MockAdapter;

  beforeEach(async () => {
    mock = new MockAdapter(api);
    useAuthStore.getState().clearSession();
    localStorage.clear();
    replaceMock.mockClear();
  });

  afterEach(() => mock.restore());

  it("redirects to /login when no token", async () => {
    render(<AuthGuard><div>protected</div></AuthGuard>);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("protected")).toBeNull();
  });

  it("renders children after /auth/me succeeds", async () => {
    useAuthStore.getState().setSession("u_7", { id: 7, username: "alice" });
    mock.onGet("/auth/me").reply(200, { id: 7, username: "alice", created_at: "2026-04-25T10:00:00Z" });
    render(<AuthGuard><div>protected</div></AuthGuard>);
    expect(await screen.findByText("protected")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("clears session and redirects when /auth/me returns 401", async () => {
    useAuthStore.getState().setSession("u_7", { id: 7, username: "alice" });
    mock.onGet("/auth/me").reply(401, { detail: "invalid_token" });
    render(<AuthGuard><div>protected</div></AuthGuard>);
    await waitFor(() => expect(useAuthStore.getState().token).toBeNull());
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
  });
});
