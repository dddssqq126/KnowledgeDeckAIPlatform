import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import McpToolsPage from "./page";
import { loadMcpTools } from "../../../lib/mcp-tools";

vi.mock("../../../lib/mcp-tools", () => ({
  loadMcpTools: vi.fn(),
  registerMcpTool: vi.fn(),
  updateMcpToolStatus: vi.fn(),
  deleteMcpTool: vi.fn(),
}));

describe("McpToolsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(loadMcpTools).mockResolvedValue([
      {
        id: 1,
        name: "System LLM Info",
        queryName: "query_llm_info",
        serverName: "system_info_server",
        description: "Returns model info.",
        transport: "in-process",
        method: "POST",
        endpoint: "app.shared.api.llm_info",
        templateId: "query_llm_info:v1",
        timeoutSec: 5,
        status: "enabled",
        inputSchema: {},
        outputSchema: { label: "string", model_id: "string" },
        builtIn: true,
        handlerKey: "llm_info",
        updatedAt: "2026-07-02T00:00:00Z",
      },
    ]);
  });

  it("disables delete for built-in tools", async () => {
    render(<McpToolsPage />);

    expect(await screen.findAllByText("System LLM Info")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });
});
