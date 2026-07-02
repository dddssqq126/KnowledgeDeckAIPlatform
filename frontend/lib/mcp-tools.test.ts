import { afterEach, describe, expect, it, vi } from "vitest";

import { registerMcpTool, type McpToolDraft } from "./mcp-tools";

const draft: McpToolDraft = {
  name: "Custom Tool",
  queryName: "query_custom_tool",
  serverName: "custom_server",
  description: "Custom MCP tool.",
  transport: "http",
  endpoint: "https://example.test/mcp",
  templateId: "custom:v1",
  timeoutSec: 10,
  inputSchema: {},
  outputSchema: {},
};

describe("registerMcpTool", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("uses crypto.randomUUID when it is available", () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "random-uuid",
    });

    const [tool] = registerMcpTool(draft, []);

    expect(tool.id).toBe("custom-random-uuid");
  });

  it("falls back to getRandomValues when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]);
        return bytes;
      },
    });

    const [tool] = registerMcpTool(draft, []);

    expect(tool.id).toBe("custom-00010203-0405-4607-8809-0a0b0c0d0e0f");
  });

  it("falls back to timestamp and Math.random when crypto is unavailable", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-02T00:00:00.000Z"));
    vi.stubGlobal("crypto", undefined);
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0.5);

    const [tool] = registerMcpTool(draft, []);

    expect(tool.id).toBe("custom-mcl5mo00-i");
    randomSpy.mockRestore();
  });
});
