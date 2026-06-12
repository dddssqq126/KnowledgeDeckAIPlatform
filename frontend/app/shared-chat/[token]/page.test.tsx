import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SharedChatPage from "./page";
import { getSharedChat } from "../../../lib/chat";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "share-token" }),
}));

vi.mock("../../../components/AuthGuard", () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../../../lib/chat", () => ({
  getSharedChat: vi.fn(),
}));

describe("SharedChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSharedChat).mockResolvedValue({
      id: 1,
      title: "Shared RAG answer",
      created_at: "2026-05-06T00:00:00Z",
      updated_at: "2026-05-06T01:00:00Z",
      messages: [
        {
          id: 11,
          role: "user",
          content: "What changed?",
          citations: null,
          created_at: "2026-05-06T00:10:00Z",
        },
        {
          id: 12,
          role: "assistant",
          content: "The answer cites a file.",
          citations: [{ file_id: 7, filename: "source.pdf" }],
          created_at: "2026-05-06T00:11:00Z",
        },
      ],
    });
  });

  it("loads and renders only the shared conversation with read-only sources", async () => {
    render(<SharedChatPage />);

    expect(await screen.findByText("Shared RAG answer")).toBeInTheDocument();
    expect(screen.getByText("What changed?")).toBeInTheDocument();
    expect(screen.getByText("The answer cites a file.")).toBeInTheDocument();
    expect(screen.getByText("source.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download source.pdf/i })).not.toBeInTheDocument();
    expect(getSharedChat).toHaveBeenCalledWith("share-token");
  });
});
