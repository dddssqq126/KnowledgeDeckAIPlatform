import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "./AuthGuard";
import { useAuthStore } from "../lib/auth-store";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: replaceMock }),
}));

describe("AuthGuard", () => {
  beforeEach(() => {
    useAuthStore.getState().clearSession();
    localStorage.clear();
    replaceMock.mockClear();
  });

  it("redirects to /login when no user", async () => {
    render(<AuthGuard><div>protected</div></AuthGuard>);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("protected")).toBeNull();
  });

  it("renders children when user exists", async () => {
    useAuthStore.getState().setSession({ id: 7, username: "alice" });
    render(<AuthGuard><div>protected</div></AuthGuard>);
    expect(await screen.findByText("protected")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
