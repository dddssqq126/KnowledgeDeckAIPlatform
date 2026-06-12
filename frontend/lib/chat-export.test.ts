import { beforeEach, describe, expect, it, vi } from "vitest";

import { exportAssistantAnswer, exportChatSession } from "./chat-export";
import { downloadTextFile } from "./download";
import type { ChatMessage } from "./chat";

vi.mock("./download", () => ({
  downloadTextFile: vi.fn(),
  safeFilename: (value: string, fallback = "download") => value || fallback,
}));

describe("chat export helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exports a full chat session as markdown", () => {
    exportChatSession({
      title: "RAG chat",
      messages: [
        message(1, "user", "Question?", null),
        message(2, "assistant", "Answer.", [{ file_id: 9, filename: "source.pdf" }]),
      ],
    });

    expect(downloadTextFile).toHaveBeenCalledWith(
      expect.stringContaining("# RAG chat"),
      "RAG chat.md",
    );
    const content = vi.mocked(downloadTextFile).mock.calls[0][0];
    expect(content).toContain("## User");
    expect(content).toContain("Question?");
    expect(content).toContain("## Assistant");
    expect(content).toContain("- source.pdf");
  });

  it("exports one assistant answer as markdown", () => {
    exportAssistantAnswer(
      message(3, "assistant", "Single answer", [{ file_id: 4, filename: "x.txt" }]),
      "answer",
    );

    expect(downloadTextFile).toHaveBeenCalledWith(
      expect.stringContaining("Single answer"),
      "answer.md",
    );
  });
});

function message(
  id: number,
  role: ChatMessage["role"],
  content: string,
  citations: ChatMessage["citations"],
): ChatMessage {
  return {
    id,
    role,
    content,
    citations,
    created_at: "2026-05-06T00:00:00Z",
  };
}
