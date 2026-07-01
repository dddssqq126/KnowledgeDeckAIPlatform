import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "./ChatInput";

function renderInput(onSend = vi.fn()) {
  const view = render(
    <ChatInput knowledgeBases={[]} disabled={false} onSend={onSend} />,
  );
  const fileInput = view.container.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  return { ...view, fileInput, onSend };
}

describe("ChatInput attachments", () => {
  it("shows a selected valid file and sends it with the message", async () => {
    const { fileInput, onSend } = renderInput();
    const file = new File(["Sub Main()"], "Macro.bas", { type: "text/plain" });

    fireEvent.change(fileInput, { target: { files: [file] } });
    expect(screen.getByText("Macro.bas")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Summarize this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend).toHaveBeenCalledWith(
      "Summarize this",
      true,
      null,
      false,
      [file],
    );
  });

  it("allows file-only submit with a deterministic prompt", async () => {
    const { fileInput, onSend } = renderInput();
    const file = new File(["hello"], "notes.word.txt", { type: "text/plain" });

    fireEvent.change(fileInput, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend).toHaveBeenCalledWith(
      "Please answer using the attached file(s).",
      true,
      null,
      false,
      [file],
    );
  });

  it("rejects unsupported extensions and does not send them", () => {
    const { fileInput, onSend } = renderInput();
    const file = new File(["binary"], "legacy.ppt", {
      type: "application/vnd.ms-powerpoint",
    });

    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unsupported file type: legacy.ppt.",
    );
    expect(screen.queryByText("legacy.ppt")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("caps attachments at five files and shows a validation message", async () => {
    const user = userEvent.setup();
    const { fileInput, onSend } = renderInput();
    const files = Array.from(
      { length: 6 },
      (_, index) => new File([String(index)], `file-${index}.txt`),
    );

    await user.upload(fileInput, files);

    expect(screen.getByText("file-0.txt")).toBeInTheDocument();
    expect(screen.getByText("file-4.txt")).toBeInTheDocument();
    expect(screen.queryByText("file-5.txt")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Attach up to 5 files per message.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith(
      "Please answer using the attached file(s).",
      true,
      null,
      false,
      files.slice(0, 5),
    );
  });

  it("hides attachment controls when attachments are disabled", () => {
    render(
      <ChatInput
        knowledgeBases={[]}
        disabled={false}
        onSend={vi.fn()}
        allowAttachments={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Attach files" }),
    ).not.toBeInTheDocument();
  });
});
