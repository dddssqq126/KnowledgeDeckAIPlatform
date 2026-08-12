import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DropUpload } from "./DropUpload";

function renderDropUpload() {
  const view = render(<DropUpload kbId={1} onAllUploaded={vi.fn()} />);
  const fileInput = view.container.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  return { ...view, fileInput };
}

describe("DropUpload accepted file types", () => {
  it("queues bas files and skips legacy ppt files", () => {
    const { fileInput } = renderDropUpload();
    const bas = new File(["Sub Main()"], "Macro.bas", { type: "text/plain" });
    const ppt = new File(["binary"], "legacy.ppt", {
      type: "application/vnd.ms-powerpoint",
    });

    expect(fileInput).toHaveAttribute(
      "accept",
      ".txt,.pdf,.cs,.md,.docx,.pptx,.py,.html,.css,.bas",
    );

    fireEvent.change(fileInput, { target: { files: [bas, ppt] } });

    expect(screen.getByText("Macro.bas")).toBeInTheDocument();
    expect(screen.queryByText("legacy.ppt")).not.toBeInTheDocument();
    expect(screen.getByText("1 file skipped (unsupported format).")).toBeInTheDocument();
  });

  it("provides a PDF/PPTX-only image extraction input", () => {
    const view = renderDropUpload();
    const inputs = view.container.querySelectorAll('input[type="file"]');
    expect(inputs[1]).toHaveAttribute("accept", ".pdf,.pptx");
    expect(screen.getByRole("button", { name: /extract images/i })).toBeInTheDocument();
  });
});
