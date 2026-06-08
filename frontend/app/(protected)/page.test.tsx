import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "./page";
import { downloadChatInputFile, getSession, sendMessageFeedback, shareChatSession, streamChat } from "../../lib/chat";

const chatInputMockState = vi.hoisted(() => ({ deepMode: false }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("sid=1"),
}));

vi.mock("../../components/ChatInput", () => ({
  ChatInput: ({ onSend }: any) => (
    <div data-testid="chat-input">
      <label>
        <input
          aria-label="deepmmode"
          type="checkbox"
          onChange={(event) => {
            chatInputMockState.deepMode = event.currentTarget.checked;
          }}
        />
        deepmmode
      </label>
      <button
        type="button"
        onClick={() =>
          onSend("Deep question", true, null, chatInputMockState.deepMode)
        }
      >
        Send test message
      </button>
    </div>
  ),
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
  downloadChatInputFile: vi.fn(),
  getSession: vi.fn(),
  sendMessageFeedback: vi.fn(),
  shareChatSession: vi.fn(),
  streamChat: vi.fn(),
}));

describe("ChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chatInputMockState.deepMode = false;
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


  it("shows historical chat input files and downloads them", async () => {
    vi.mocked(getSession).mockResolvedValueOnce({
      id: 1,
      title: "RAG onboarding checklist",
      created_at: "2026-05-06T00:00:00Z",
      updated_at: "2026-05-06T01:00:00Z",
      messages: [
        {
          id: 31,
          role: "user",
          content: "Please read this",
          citations: null,
          created_at: "2026-05-06T00:09:00Z",
          input_files: [
            {
              id: 44,
              filename: "input.pdf",
              extension: "pdf",
              size_bytes: 1234,
              created_at: "2026-05-06T00:09:01Z",
            },
          ],
        },
      ],
    });
    vi.mocked(downloadChatInputFile).mockResolvedValueOnce(undefined);

    render(<ChatPage />);

    expect(await screen.findByText("input.pdf")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Download input file input.pdf" }),
    );

    await waitFor(() => {
      expect(downloadChatInputFile).toHaveBeenCalledWith(44, "input.pdf");
    });
  });

  it("sends deep mode in the stream request when deepmmode is checked", async () => {
    vi.mocked(streamChat).mockResolvedValueOnce(undefined);
    render(<ChatPage />);

    await screen.findByText("Exportable answer");
    fireEvent.click(screen.getByRole("checkbox", { name: "deepmmode" }));
    fireEvent.click(screen.getByRole("button", { name: "Send test message" }));

    await waitFor(() => {
      expect(streamChat).toHaveBeenCalledWith(
        {
          session_id: 1,
          message: "Deep question",
          use_rag: true,
          kb_ids: null,
          deep_mode: true,
        },
        expect.any(Object),
      );
    });
  });

  it("records like and dislike feedback for assistant messages", async () => {
    vi.mocked(sendMessageFeedback)
      .mockResolvedValueOnce({
        message_id: 21,
        feedback: "like",
        content: "Exportable answer",
        updated_at: "2026-05-06T00:11:00Z",
      })
      .mockResolvedValueOnce({
        message_id: 21,
        feedback: "dislike",
        content: "Exportable answer",
        updated_at: "2026-05-06T00:12:00Z",
      });
    render(<ChatPage />);

    await screen.findByText("Exportable answer");
    fireEvent.click(screen.getByRole("button", { name: "Like response" }));

    await waitFor(() => {
      expect(sendMessageFeedback).toHaveBeenCalledWith(21, "like");
    });

    fireEvent.click(screen.getByRole("button", { name: "Dislike response" }));

    await waitFor(() => {
      expect(sendMessageFeedback).toHaveBeenCalledWith(21, "dislike");
    });
  });

  it("shows feedback actions immediately after a streamed assistant message is done", async () => {
    vi.mocked(getSession)
      .mockResolvedValueOnce({
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
      })
      .mockResolvedValueOnce({
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
          {
            id: 99,
            role: "assistant",
            content: "Streamed answer",
            citations: null,
            created_at: "2026-05-06T00:11:00Z",
          },
        ],
      });
    vi.mocked(streamChat).mockImplementationOnce(async (_request, handlers) => {
      handlers.onToken("Streamed answer");
      handlers.onDone({ message_id: 99 });
    });
    render(<ChatPage />);

    await screen.findByText("Exportable answer");
    fireEvent.click(screen.getByRole("button", { name: "Send test message" }));

    expect(await screen.findByText("Streamed answer")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Like response" })).toHaveLength(2);
  });

  it("shows a feedback error instead of silently failing", async () => {
    vi.mocked(sendMessageFeedback).mockRejectedValueOnce(new Error("feedback failed"));
    render(<ChatPage />);

    await screen.findByText("Exportable answer");
    fireEvent.click(screen.getByRole("button", { name: "Like response" }));

    expect(await screen.findByText("Feedback error: feedback failed")).toBeInTheDocument();
  });
});
