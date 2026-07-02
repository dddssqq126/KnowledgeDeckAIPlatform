"use client";

import { api } from "./api";

export type McpToolStatus = "enabled" | "disabled";
export type McpTransport = "in-process" | "stdio" | "http";
export type McpMethod = "GET" | "POST";

export type McpTool = {
  id: number;
  name: string;
  queryName: string;
  serverName: string;
  description: string;
  transport: McpTransport;
  method: McpMethod;
  endpoint: string;
  templateId: string;
  timeoutSec: number;
  status: McpToolStatus;
  inputSchema: Record<string, string>;
  outputSchema: Record<string, string>;
  builtIn: boolean;
  handlerKey: string;
  updatedAt: string;
};

export type McpToolDraft = {
  name: string;
  queryName: string;
  serverName: string;
  description: string;
  transport: McpTransport;
  method: McpMethod;
  endpoint: string;
  templateId: string;
  timeoutSec: number;
  inputSchema: Record<string, string>;
  outputSchema: Record<string, string>;
};

export async function loadMcpTools(): Promise<McpTool[]> {
  const res = await api.get<McpTool[]>("/mcp-tools");
  return res.data;
}

export async function registerMcpTool(draft: McpToolDraft): Promise<McpTool> {
  const res = await api.post<McpTool>("/mcp-tools", draft);
  return res.data;
}

export async function updateMcpToolStatus(
  id: number,
  status: McpToolStatus,
): Promise<McpTool> {
  const res = await api.patch<McpTool>(`/mcp-tools/${id}/status`, { status });
  return res.data;
}

export async function deleteMcpTool(id: number): Promise<void> {
  await api.delete(`/mcp-tools/${id}`);
}
