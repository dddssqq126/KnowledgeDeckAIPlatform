import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RagDatabasesPage from "./page";
import {
  downloadKnowledgeFile,
  listFileTags,
  listFiles,
  listKnowledgeBases,
} from "../../../lib/knowledge-bases";

vi.mock("../../../lib/knowledge-bases", () => ({
  downloadKnowledgeFile: vi.fn().mockResolvedValue(undefined),
  listFileTags: vi.fn(),
  listFiles: vi.fn(),
  listKnowledgeBases: vi.fn(),
}));

describe("RagDatabasesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listKnowledgeBases).mockResolvedValue([
      {
        id: 1,
        name: "Engineering Handbook",
        description: null,
        file_count: 2,
        created_at: "2026-05-06T00:00:00Z",
      },
      {
        id: 2,
        name: "Product Research",
        description: null,
        file_count: 1,
        created_at: "2026-05-06T00:00:00Z",
      },
    ]);
    vi.mocked(listFiles).mockImplementation(async (kbId: number) =>
      kbId === 1
        ? [
            file(11, 1, "react_hooks.txt", "txt"),
            file(12, 1, "postgres_indexing.pdf", "pdf"),
          ]
        : [file(21, 2, "market_map.pdf", "pdf")],
    );
    vi.mocked(listFileTags).mockResolvedValue([]);
  });

  it("renders imported files with download buttons", async () => {
    render(<RagDatabasesPage />);

    expect(await screen.findByText("react_hooks.txt")).toBeInTheDocument();
    expect(screen.getByText("market_map.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Download react_hooks.txt" }));

    expect(downloadKnowledgeFile).toHaveBeenCalledWith(11, "react_hooks.txt");
  });

  it("shows real chunk count and tag chips per file", async () => {
    vi.mocked(listKnowledgeBases).mockResolvedValue([
      {
        id: 1,
        name: "kb",
        description: null,
        file_count: 1,
        created_at: "2026-05-06T00:00:00Z",
      },
    ]);
    vi.mocked(listFiles).mockResolvedValue([
      file(1, 1, "k8s.txt", "txt"),
    ]);
    vi.mocked(listFileTags).mockResolvedValue([
      {
        file_id: 1,
        doc_type: "guide",
        intent: "how_to",
        tags_topic: ["kubernetes"],
        chunk_count: 12,
      },
    ]);

    render(<RagDatabasesPage />);

    expect(await screen.findByText("k8s.txt")).toBeInTheDocument();
    expect(screen.getByText("guide")).toBeInTheDocument();
    expect(screen.getByText("#kubernetes")).toBeInTheDocument();
    expect(screen.getByText(/12 vectors/)).toBeInTheDocument();
  });

  it("filters imported files by filename", async () => {
    render(<RagDatabasesPage />);

    await screen.findByText("react_hooks.txt");
    fireEvent.change(screen.getByPlaceholderText("Search imported files"), {
      target: { value: "postgres" },
    });

    expect(screen.getByText("postgres_indexing.pdf")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("react_hooks.txt")).not.toBeInTheDocument();
      expect(screen.queryByText("market_map.pdf")).not.toBeInTheDocument();
    });
  });
});

function file(id: number, knowledgeBaseId: number, filename: string, extension: string) {
  return {
    id,
    knowledge_base_id: knowledgeBaseId,
    filename,
    extension,
    size_bytes: 1024,
    status: "indexed" as const,
    status_error: null,
    created_at: "2026-05-06T00:00:00Z",
  };
}
