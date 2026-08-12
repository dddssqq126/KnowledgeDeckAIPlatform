import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RelatedImageStrip } from "./RelatedImageStrip";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(async () => ({ data: new Blob(["image"]) })),
  },
}));

describe("RelatedImageStrip", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:test-image"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a related image and opens its source details", async () => {
    render(
      <RelatedImageStrip
        images={[
          {
            id: 9,
            name: "季度營收圖",
            source_filename: "sales.pptx",
            source_file_id: 4,
            source_extension: "pptx",
            page_number: 3,
            content_url: "/knowledge-bases/images/9/content",
            source_download_url: "/knowledge-bases/files/4/download",
          },
        ]}
      />,
    );

    await waitFor(() => expect(screen.getByText("季度營收圖")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Open 季度營收圖" }));

    expect(screen.getByRole("dialog", { name: "季度營收圖" })).toBeInTheDocument();
    expect(screen.getAllByText("sales.pptx · PPTX slide 3").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /download source file/i })).toBeInTheDocument();
  });
});
