import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "./page";
import { getSession, shareChatSession } from "../../lib/chat";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("sid=1"),
}));

vi.mock("../../components/ChatInput", () => ({
  ChatInput: () => <div data-testid="chat-input" />,
}));

vi.mock("../../lib/chat-store", () => ({
  useChatSessionsStore: (selector: any) =>
    selector({
      sessions: [
        {
          id: 1,
          title: "RAG onboarding checklist",
          created_at: "2026-05-06T00:00:00Z",
          updated_at: "2026-05-06T01:00:00Z",
        },
      ],
      loaded: true,
      refresh: vi.fn(),
      newChat: vi.fn(),
      bumpUpdatedAt: vi.fn(),
    }),
}));

vi.mock("../../lib/kb-store", () => ({
  useKbStore: (selector: any) =>
    selector({ kbs: [], loaded: true, refresh: vi.fn() }),
}));

vi.mock("../../lib/llm-info", () => ({
  useLlmInfo: () => ({ label: "Mock model", model_id: "mock" }),
}));

vi.mock("../../lib/chat", () => ({
  getSession: vi.fn(),
  shareChatSession: vi.fn(),
  streamChat: vi.fn(),
}));

describe("ChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.mocked(getSession).mockResolvedValue({
      id: 1,
      title: "RAG onboarding checklist",
      created_at: "2026-05-06T00:00:00Z",
      updated_at: "2026-05-06T01:00:00Z",
      messages: [
        {
          id: 21,
          role: "assistant",
          content: "Exportable answer",
          citations: null,
          created_at: "2026-05-06T00:10:00Z",
        },
      ],
    });
    vi.mocked(shareChatSession).mockResolvedValue({
      token: "abc123",
      url_path: "/shared-chat/abc123",
    });
  });

  it("creates and copies an authenticated shared chat link", async () => {
    render(<ChatPage />);

    await screen.findByText("Exportable answer");
    fireEvent.click(screen.getByRole("button", { name: "Share" }));

    await waitFor(() => {
      expect(shareChatSession).toHaveBeenCalledWith(1);
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "http://localhost:3000/shared-chat/abc123",
      );
    });
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows source filenames without metadata tag chips", async () => {
    vi.mocked(getSession).mockResolvedValueOnce({
      id: 1,
      title: "RAG onboarding checklist",
      created_at: "2026-05-06T00:00:00Z",
      updated_at: "2026-05-06T01:00:00Z",
      messages: [
        {
          id: 22,
          role: "assistant",
          content: "Tagged citation answer",
          citations: [
            {
              file_id: 7,
              filename: "source.pdf",
              doc_type: "standard",
              vendor: "3gpp",
              platform: "5g_nr",
              knowledge_type: "spec",
              tags_topic: ["ran"],
            },
          ],
          created_at: "2026-05-06T00:10:00Z",
        },
      ],
    });

    render(<ChatPage />);

    expect(await screen.findByText("source.pdf")).toBeInTheDocument();
    expect(screen.queryByText("3gpp")).not.toBeInTheDocument();
    expect(screen.queryByText("5g_nr")).not.toBeInTheDocument();
    expect(screen.queryByText("spec")).not.toBeInTheDocument();
    expect(screen.queryByText("#ran")).not.toBeInTheDocument();
  });
});
