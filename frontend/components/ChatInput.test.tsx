import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "./ChatInput";

describe("ChatInput", () => {
  it("sends text-only messages without requiring an attachment", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    render(<ChatInput knowledgeBases={[]} disabled={false} onSend={onSend} />);

    await user.type(
      screen.getByPlaceholderText(/Ask anything/),
      "Plain text question",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend).toHaveBeenCalledWith(
      "Plain text question",
      true,
      null,
      false,
      [],
    );
  });
});
