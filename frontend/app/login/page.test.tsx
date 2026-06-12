import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";
import { useAuthStore } from "../../lib/auth-store";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams("username=alice"),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    useAuthStore.getState().clearSession();
    useAuthStore.getState().setExternalUser("external-user");
    localStorage.clear();
    window.history.pushState({}, "", "/login?username=alice");
    replaceMock.mockClear();
  });

  it("stores the external username and redirects home", async () => {
    render(<LoginPage />);

    await waitFor(() => {
      expect(useAuthStore.getState().externalUsername).toBe("alice");
    });
    expect(localStorage.getItem("knowledgedeck-external-username")).toBe("alice");
    expect(replaceMock).toHaveBeenCalledWith("/");
  });
});
