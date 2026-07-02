"use client";

export type McpToolStatus = "enabled" | "disabled";
export type McpTransport = "in-process" | "stdio" | "http";

export type McpTool = {
  id: string;
  name: string;
  queryName: string;
  serverName: string;
  description: string;
  transport: McpTransport;
  endpoint: string;
  templateId: string;
  timeoutSec: number;
  status: McpToolStatus;
  inputSchema: Record<string, string>;
  outputSchema: Record<string, string>;
  builtIn: boolean;
  updatedAt: string;
};

export type McpToolDraft = {
  name: string;
  queryName: string;
  serverName: string;
  description: string;
  transport: McpTransport;
  endpoint: string;
  templateId: string;
  timeoutSec: number;
  inputSchema: Record<string, string>;
  outputSchema: Record<string, string>;
};

const STORAGE_KEY = "knowledgedeck:mcp-tools:v1";

export const BUILT_IN_MCP_TOOLS: McpTool[] = [
  {
    id: "builtin-query-bom-cost",
    name: "BOM Cost",
    queryName: "query_bom_cost",
    serverName: "business_query_server",
    description: "Fixed query template for BOM cost lookup.",
    transport: "in-process",
    endpoint: "backend/mcp_servers/business_query_server.py",
    templateId: "query_bom_cost:v1",
    timeoutSec: 10,
    status: "enabled",
    inputSchema: {
      part_no: "string",
      project_id: "string",
    },
    outputSchema: {
      part_no: "string",
      unit_price: "number",
      currency: "string",
      vendor: "string",
      updated_at: "string",
    },
    builtIn: true,
    updatedAt: "2026-07-01T00:00:00.000Z",
  },
  {
    id: "builtin-query-project-spec",
    name: "Project Spec",
    queryName: "query_project_spec",
    serverName: "business_query_server",
    description: "Stubbed schema for project specification lookup.",
    transport: "in-process",
    endpoint: "backend/mcp_servers/business_query_server.py",
    templateId: "",
    timeoutSec: 10,
    status: "disabled",
    inputSchema: {
      project_id: "string",
    },
    outputSchema: {
      project_id: "string",
      spec_name: "string",
      updated_at: "string",
    },
    builtIn: true,
    updatedAt: "2026-07-01T00:00:00.000Z",
  },
  {
    id: "builtin-query-vendor-quote",
    name: "Vendor Quote",
    queryName: "query_vendor_quote",
    serverName: "business_query_server",
    description: "Stubbed schema for vendor quote lookup.",
    transport: "in-process",
    endpoint: "backend/mcp_servers/business_query_server.py",
    templateId: "",
    timeoutSec: 10,
    status: "disabled",
    inputSchema: {
      vendor_name: "string",
      part_no: "string | null",
    },
    outputSchema: {
      vendor: "string",
      part_no: "string",
      unit_price: "number",
      currency: "string",
      updated_at: "string",
    },
    builtIn: true,
    updatedAt: "2026-07-01T00:00:00.000Z",
  },
];

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function loadMcpTools(): McpTool[] {
  if (!canUseStorage()) return BUILT_IN_MCP_TOOLS;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return BUILT_IN_MCP_TOOLS;
  try {
    const custom = JSON.parse(raw) as McpTool[];
    if (!Array.isArray(custom)) return BUILT_IN_MCP_TOOLS;
    return mergeBuiltIns(custom);
  } catch {
    return BUILT_IN_MCP_TOOLS;
  }
}

export function saveMcpTools(tools: McpTool[]): void {
  if (!canUseStorage()) return;
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(tools.filter((tool) => !tool.builtIn)),
  );
}

function createUniqueId(): string {
  const browserCrypto = globalThis.crypto;

  if (typeof browserCrypto?.randomUUID === "function") {
    return browserCrypto.randomUUID();
  }

  if (typeof browserCrypto?.getRandomValues === "function") {
    const bytes = browserCrypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;

    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
    return [
      hex.slice(0, 4).join(""),
      hex.slice(4, 6).join(""),
      hex.slice(6, 8).join(""),
      hex.slice(8, 10).join(""),
      hex.slice(10, 16).join(""),
    ].join("-");
  }

  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function registerMcpTool(draft: McpToolDraft, existing: McpTool[]): McpTool[] {
  const id = `custom-${createUniqueId()}`;
  const tool: McpTool = {
    ...draft,
    id,
    status: "enabled",
    builtIn: false,
    updatedAt: new Date().toISOString(),
  };
  const next = [tool, ...existing];
  saveMcpTools(next);
  return next;
}

export function updateMcpToolStatus(
  id: string,
  status: McpToolStatus,
  existing: McpTool[],
): McpTool[] {
  const next = existing.map((tool) =>
    tool.id === id ? { ...tool, status, updatedAt: new Date().toISOString() } : tool,
  );
  saveMcpTools(next);
  return next;
}

export function deleteMcpTool(id: string, existing: McpTool[]): McpTool[] {
  const next = existing.filter((tool) => tool.id !== id || tool.builtIn);
  saveMcpTools(next);
  return next;
}

function mergeBuiltIns(custom: McpTool[]): McpTool[] {
  const customIds = new Set(custom.map((tool) => tool.id));
  const missingBuiltIns = BUILT_IN_MCP_TOOLS.filter((tool) => !customIds.has(tool.id));
  return [...missingBuiltIns, ...custom];
}
