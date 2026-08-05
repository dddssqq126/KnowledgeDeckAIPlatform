import { describe, expect, it } from "vitest";

import { buildStreamFormData } from "./chat";

describe("buildStreamFormData", () => {
  it("includes payload, deep mode, and all attachment files", () => {
    const first = new File(["alpha"], "a.txt", { type: "text/plain" });
    const second = new File(["beta"], "b.md", { type: "text/markdown" });

    const form = buildStreamFormData({
      session_id: 12,
      message: "Use these",
      use_rag: true,
      kb_ids: [1, 2],
      deep_mode: true,
      custom_role: "Answer as a concise reviewer.",
      attachments: [first, second],
    });

    expect(form.get("session_id")).toBe("12");
    expect(form.get("message")).toBe("Use these");
    expect(form.get("use_rag")).toBe("true");
    expect(form.get("kb_ids")).toBe("[1,2]");
    expect(form.get("deep_mode")).toBe("true");
    expect(form.get("custom_role")).toBe("Answer as a concise reviewer.");
    expect(JSON.parse(String(form.get("payload")))).toEqual({
      session_id: 12,
      message: "Use these",
      use_rag: true,
      kb_ids: [1, 2],
      deep_mode: true,
      custom_role: "Answer as a concise reviewer.",
    });
    expect(form.getAll("files")).toEqual([first, second]);
  });
});
