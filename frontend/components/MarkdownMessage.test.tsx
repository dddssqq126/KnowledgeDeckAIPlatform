import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MarkdownMessage } from "./MarkdownMessage";
import { downloadBlob } from "../lib/download";

vi.mock("../lib/download", () => ({
  downloadBlob: vi.fn(),
}));

describe("MarkdownMessage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("renders markdown tables with a copy button", async () => {
    render(
      <MarkdownMessage content={"| Name | Value |\n| --- | --- |\n| A | 1 |"} />,
    );

    expect(screen.getByText("Table")).toBeInTheDocument();
    expect(screen.getByText("Table").closest("div")).toHaveClass("bg-muted");
    fireEvent.click(screen.getByRole("button", { name: "Copy table" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "Name\tValue\nA\t1",
      );
    });
  });

  it("downloads markdown tables as Excel-compatible xls files", async () => {
    render(
      <MarkdownMessage content={"| Name | Value |\n| --- | --- |\n| A&B | <1> |"} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Download Excel" }));

    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "table-export.xls");
    const blob = vi.mocked(downloadBlob).mock.calls[0][0] as Blob;
    const xml = await blobToText(blob);
    expect(xml).toContain("Excel.Sheet");
    expect(xml).toContain("A&amp;B");
    expect(xml).toContain("&lt;1&gt;");
  });

  it("uses highlighted code cards for explicit fenced code", () => {
    render(
      <MarkdownMessage content={"```ts\nconst answer: number = 42;\n```"} />,
    );

    expect(screen.getByText("ts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    expect(screen.getByText("const")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders prose-like unlabeled fences as wrapped plain text", () => {
    render(
      <MarkdownMessage
        content={"```\nThis is a normal note that should not look like source code.\n```"}
      />,
    );

    expect(screen.queryByRole("button", { name: "Copy code" })).not.toBeInTheDocument();
    expect(
      screen.getByText("This is a normal note that should not look like source code."),
    ).toHaveClass("whitespace-pre-wrap");
  });
});

function blobToText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}
