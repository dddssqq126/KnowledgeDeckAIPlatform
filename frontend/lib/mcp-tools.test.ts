import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { api } from "./api";
import {
  deleteMcpTool,
  loadMcpTools,
  registerMcpTool,
  updateMcpToolStatus,
} from "./mcp-tools";

describe("mcp-tools API client", () => {
  let mock: MockAdapter;

  beforeEach(() => {
    mock = new MockAdapter(api);
  });

  afterEach(() => {
    mock.restore();
  });

  it("loadMcpTools hits GET /mcp-tools", async () => {
    mock.onGet("/mcp-tools").reply(200, [
      {
        id: 1,
        name: "System LLM Info",
        queryName: "query_llm_info",
        serverName: "system_info_server",
        description: "Returns model info.",
        transport: "in-process",
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

    const tools = await loadMcpTools();

    expect(tools[0].queryName).toBe("query_llm_info");
    expect(tools[0].builtIn).toBe(true);
  });

  it("registerMcpTool posts the draft", async () => {
    mock.onPost("/mcp-tools").reply((config) => {
      expect(JSON.parse(config.data)).toEqual({
        name: "Local Status",
        queryName: "query_local_status",
        serverName: "business_query_server",
        description: "Checks status.",
        transport: "in-process",
        endpoint: "backend/mcp_servers/business_query_server.py",
        templateId: "",
        timeoutSec: 10,
        inputSchema: { part_no: "string" },
        outputSchema: { status: "string" },
      });
      return [
        201,
        {
          id: 2,
          name: "Local Status",
          queryName: "query_local_status",
          serverName: "business_query_server",
          description: "Checks status.",
          transport: "in-process",
          endpoint: "backend/mcp_servers/business_query_server.py",
          templateId: "",
          timeoutSec: 10,
          status: "enabled",
          inputSchema: { part_no: "string" },
          outputSchema: { status: "string" },
          builtIn: false,
          handlerKey: "",
          updatedAt: "2026-07-02T00:00:00Z",
        },
      ];
    });

    const created = await registerMcpTool({
      name: "Local Status",
      queryName: "query_local_status",
      serverName: "business_query_server",
      description: "Checks status.",
      transport: "in-process",
      endpoint: "backend/mcp_servers/business_query_server.py",
      templateId: "",
      timeoutSec: 10,
      inputSchema: { part_no: "string" },
      outputSchema: { status: "string" },
    });

    expect(created.id).toBe(2);
  });

  it("updateMcpToolStatus patches the status", async () => {
    mock.onPatch("/mcp-tools/2/status").reply((config) => {
      expect(JSON.parse(config.data)).toEqual({ status: "disabled" });
      return [
        200,
        {
          id: 2,
          name: "Local Status",
          queryName: "query_local_status",
          serverName: "business_query_server",
          description: "",
          transport: "in-process",
          endpoint: "",
          templateId: "",
          timeoutSec: 10,
          status: "disabled",
          inputSchema: {},
          outputSchema: {},
          builtIn: false,
          handlerKey: "",
          updatedAt: "2026-07-02T00:00:00Z",
        },
      ];
    });

    const updated = await updateMcpToolStatus(2, "disabled");

    expect(updated.status).toBe("disabled");
  });

  it("deleteMcpTool hits DELETE /mcp-tools/:id", async () => {
    mock.onDelete("/mcp-tools/2").reply(204);

    await deleteMcpTool(2);
  });
});
