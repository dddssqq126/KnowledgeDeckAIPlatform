import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";
import { useAuthStore } from "../../lib/auth-store";
import { api } from "../../lib/api";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams("username=alice"),
}));

vi.mock("../../lib/api", () => ({
  api: { post: vi.fn() },
}));

describe("LoginPage", () => {
  beforeEach(() => {
    useAuthStore.getState().clearSession();
    localStorage.clear();
    window.history.pushState({}, "", "/login?username=alice");
    replaceMock.mockClear();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockResolvedValue({
      data: { token: "u_7", user: { id: 7, username: "alice" } },
    });
  });

  it("exchanges the external username for a real token then redirects home", async () => {
    render(<LoginPage />);

    await waitFor(() => {
      expect(useAuthStore.getState().token).toBe("u_7");
    });
    expect(api.post).toHaveBeenCalledWith("/auth/external", { username: "alice" });
    expect(useAuthStore.getState().user).toEqual({ id: 7, username: "alice" });
    expect(localStorage.getItem("knowledgedeck-external-username")).toBe("alice");
    expect(replaceMock).toHaveBeenCalledWith("/");
  });
});
