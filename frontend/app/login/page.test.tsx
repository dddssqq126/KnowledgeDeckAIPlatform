import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserProvider } from "../UserContext";
import LoginPage from "./page";
import { api } from "../../lib/api";
import { useAuthStore } from "../../lib/auth-store";

const replaceMock = vi.fn();
const routerMock = { replace: replaceMock };
const searchParams = new URLSearchParams("username=alice");

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParams,
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
    render(
      <UserProvider>
        <LoginPage />
      </UserProvider>,
    );

    await waitFor(() => {
      expect(useAuthStore.getState().token).toBe("u_7");
    });
    expect(api.post).toHaveBeenCalledWith("/auth/external", {
      username: "alice",
    });
    expect(api.post).not.toHaveBeenCalledWith(
      "/auth/login-records",
      expect.anything(),
    );
    expect(useAuthStore.getState().user).toEqual({ id: 7, username: "alice" });
    expect(localStorage.getItem("knowledgedeck-external-username")).toBe("alice");
    expect(replaceMock).toHaveBeenCalledWith("/");
  });
});
