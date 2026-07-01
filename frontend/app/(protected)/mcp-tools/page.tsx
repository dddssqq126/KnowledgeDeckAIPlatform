"use client";

import {
  CheckCircle2,
  DatabaseZap,
  PauseCircle,
  PlayCircle,
  PlugZap,
  Plus,
  Trash2,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  deleteMcpTool,
  loadMcpTools,
  type McpTool,
  type McpToolDraft,
  type McpTransport,
  registerMcpTool,
  updateMcpToolStatus,
} from "../../../lib/mcp-tools";

const blankDraft: McpToolDraft = {
  name: "",
  queryName: "",
  serverName: "business_query_server",
  description: "",
  transport: "in-process",
  endpoint: "backend/mcp_servers/business_query_server.py",
  templateId: "",
  timeoutSec: 10,
  inputSchema: {},
  outputSchema: {},
};

export default function McpToolsPage() {
  const [tools, setTools] = useState<McpTool[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [draft, setDraft] = useState<McpToolDraft>(blankDraft);
  const [inputSchemaText, setInputSchemaText] = useState("{\n  \"part_no\": \"string\"\n}");
  const [outputSchemaText, setOutputSchemaText] = useState("{\n  \"status\": \"string\"\n}");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loaded = loadMcpTools();
    setTools(loaded);
    setSelectedId(loaded[0]?.id ?? "");
  }, []);

  const selected = useMemo(
    () => tools.find((tool) => tool.id === selectedId) ?? tools[0] ?? null,
    [selectedId, tools],
  );
  const enabledCount = tools.filter((tool) => tool.status === "enabled").length;
  const customCount = tools.filter((tool) => !tool.builtIn).length;

  function parseSchema(value: string, label: string): Record<string, string> {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`${label} must be a JSON object`);
    }
    return Object.fromEntries(
      Object.entries(parsed).map(([key, type]) => [key, String(type)]),
    );
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    try {
      const nextDraft: McpToolDraft = {
        ...draft,
        name: draft.name.trim(),
        queryName: draft.queryName.trim(),
        serverName: draft.serverName.trim(),
        endpoint: draft.endpoint.trim(),
        templateId: draft.templateId.trim(),
        description: draft.description.trim(),
        inputSchema: parseSchema(inputSchemaText, "Input schema"),
        outputSchema: parseSchema(outputSchemaText, "Output schema"),
      };
      if (!nextDraft.name || !nextDraft.queryName || !nextDraft.serverName) {
        throw new Error("Name, query name, and server are required");
      }
      if (nextDraft.timeoutSec <= 0) {
        throw new Error("Timeout must be greater than 0");
      }
      const next = registerMcpTool(nextDraft, tools);
      setTools(next);
      setSelectedId(next[0].id);
      setDraft(blankDraft);
      setInputSchemaText("{\n  \"part_no\": \"string\"\n}");
      setOutputSchemaText("{\n  \"status\": \"string\"\n}");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid tool registration");
    }
  }

  function setStatus(tool: McpTool, status: "enabled" | "disabled") {
    setTools(updateMcpToolStatus(tool.id, status, tools));
  }

  function remove(tool: McpTool) {
    if (tool.builtIn) return;
    if (!window.confirm(`Delete ${tool.name}?`)) return;
    const next = deleteMcpTool(tool.id, tools);
    setTools(next);
    setSelectedId(next[0]?.id ?? "");
  }

  return (
    <section className="h-full overflow-auto px-5 py-5">
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <header className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-xl font-semibold">MCP Tools</h1>
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <Metric label="Registered" value={tools.length} />
              <Metric label="Enabled" value={enabledCount} />
              <Metric label="Custom" value={customCount} />
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-md border border-border bg-white px-3 py-2 text-sm text-muted-foreground">
            <DatabaseZap className="h-4 w-4" />
            <span>business_query_server</span>
          </div>
        </header>

        <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
          <form
            onSubmit={submit}
            className="space-y-3 rounded-lg border border-border bg-white p-4"
          >
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Register Tool</h2>
              <button
                type="submit"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-foreground px-3 text-sm font-medium text-background hover:opacity-90"
              >
                <Plus className="h-4 w-4" />
                Register
              </button>
            </div>

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <Field label="Name">
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="field-input"
                placeholder="Cost Lookup"
              />
            </Field>
            <Field label="Query Name">
              <input
                value={draft.queryName}
                onChange={(e) => setDraft({ ...draft, queryName: e.target.value })}
                className="field-input"
                placeholder="query_cost_lookup"
              />
            </Field>
            <Field label="Server">
              <input
                value={draft.serverName}
                onChange={(e) => setDraft({ ...draft, serverName: e.target.value })}
                className="field-input"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Transport">
                <select
                  value={draft.transport}
                  onChange={(e) =>
                    setDraft({ ...draft, transport: e.target.value as McpTransport })
                  }
                  className="field-input"
                >
                  <option value="in-process">in-process</option>
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                </select>
              </Field>
              <Field label="Timeout">
                <input
                  type="number"
                  min={1}
                  value={draft.timeoutSec}
                  onChange={(e) =>
                    setDraft({ ...draft, timeoutSec: Number(e.target.value) })
                  }
                  className="field-input"
                />
              </Field>
            </div>
            <Field label="Endpoint">
              <input
                value={draft.endpoint}
                onChange={(e) => setDraft({ ...draft, endpoint: e.target.value })}
                className="field-input"
              />
            </Field>
            <Field label="Template ID">
              <input
                value={draft.templateId}
                onChange={(e) => setDraft({ ...draft, templateId: e.target.value })}
                className="field-input"
                placeholder="query_cost_lookup:v1"
              />
            </Field>
            <Field label="Description">
              <textarea
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                className="field-input min-h-20 resize-y"
              />
            </Field>
            <Field label="Input Schema">
              <textarea
                value={inputSchemaText}
                onChange={(e) => setInputSchemaText(e.target.value)}
                spellCheck={false}
                className="field-input min-h-28 resize-y font-mono text-xs"
              />
            </Field>
            <Field label="Output Schema">
              <textarea
                value={outputSchemaText}
                onChange={(e) => setOutputSchemaText(e.target.value)}
                spellCheck={false}
                className="field-input min-h-28 resize-y font-mono text-xs"
              />
            </Field>
          </form>

          <div className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
            <div className="min-h-[520px] overflow-hidden rounded-lg border border-border bg-white">
              <div className="grid grid-cols-[minmax(170px,1fr)_140px_112px_112px] border-b border-border bg-muted/40 px-4 py-2 text-xs font-medium uppercase text-muted-foreground">
                <span>Tool</span>
                <span>Template</span>
                <span>Status</span>
                <span className="text-right">Actions</span>
              </div>
              <div className="nice-scrollbar max-h-[720px] overflow-auto">
                {tools.map((tool) => (
                  <button
                    key={tool.id}
                    type="button"
                    onClick={() => setSelectedId(tool.id)}
                    className={`grid w-full grid-cols-[minmax(170px,1fr)_140px_112px_112px] items-center gap-2 border-b border-border px-4 py-3 text-left text-sm ${
                      selected?.id === tool.id
                        ? "bg-muted/70"
                        : "bg-white hover:bg-muted/40"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <PlugZap className="h-4 w-4 text-muted-foreground" />
                        <span className="truncate font-medium">{tool.name}</span>
                      </span>
                      <span className="mt-1 block truncate text-xs text-muted-foreground">
                        {tool.queryName}
                      </span>
                    </span>
                    <span className="truncate font-mono text-xs text-muted-foreground">
                      {tool.templateId || "stub"}
                    </span>
                    <StatusBadge status={tool.status} />
                    <span className="flex justify-end gap-1">
                      {tool.status === "enabled" ? (
                        <IconButton
                          label="Disable"
                          onClick={(e) => {
                            e.stopPropagation();
                            setStatus(tool, "disabled");
                          }}
                        >
                          <PauseCircle className="h-4 w-4" />
                        </IconButton>
                      ) : (
                        <IconButton
                          label="Enable"
                          onClick={(e) => {
                            e.stopPropagation();
                            setStatus(tool, "enabled");
                          }}
                        >
                          <PlayCircle className="h-4 w-4" />
                        </IconButton>
                      )}
                      <IconButton
                        label="Delete"
                        disabled={tool.builtIn}
                        onClick={(e) => {
                          e.stopPropagation();
                          remove(tool);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </IconButton>
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <ToolDetails tool={selected} />
          </div>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2.5 py-1">
      <span>{label}</span>
      <span className="font-semibold text-foreground">{value}</span>
    </span>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium uppercase text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

function StatusBadge({ status }: { status: "enabled" | "disabled" }) {
  return (
    <span
      className={`inline-flex w-fit items-center gap-1 rounded-full border px-2 py-1 text-xs ${
        status === "enabled"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-border bg-muted text-muted-foreground"
      }`}
    >
      {status === "enabled" ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : (
        <PauseCircle className="h-3.5 w-3.5" />
      )}
      {status}
    </span>
  );
}

function IconButton({
  label,
  disabled,
  children,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  children: React.ReactNode;
  onClick: (e: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35"
    >
      {children}
    </button>
  );
}

function ToolDetails({ tool }: { tool: McpTool | null }) {
  if (!tool) {
    return (
      <div className="rounded-lg border border-border bg-white p-4 text-sm text-muted-foreground">
        No tool selected.
      </div>
    );
  }
  return (
    <aside className="space-y-4 rounded-lg border border-border bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold">{tool.name}</h2>
          <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
            {tool.queryName}
          </p>
        </div>
        <StatusBadge status={tool.status} />
      </div>

      <dl className="grid grid-cols-[112px_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Server</dt>
        <dd className="truncate">{tool.serverName}</dd>
        <dt className="text-muted-foreground">Transport</dt>
        <dd>{tool.transport}</dd>
        <dt className="text-muted-foreground">Endpoint</dt>
        <dd className="truncate font-mono text-xs">{tool.endpoint}</dd>
        <dt className="text-muted-foreground">Template</dt>
        <dd className="truncate font-mono text-xs">{tool.templateId || "stub"}</dd>
        <dt className="text-muted-foreground">Timeout</dt>
        <dd>{tool.timeoutSec}s</dd>
        <dt className="text-muted-foreground">Source</dt>
        <dd>{tool.builtIn ? "built-in" : "custom"}</dd>
      </dl>

      <div>
        <h3 className="mb-2 text-xs font-medium uppercase text-muted-foreground">
          Description
        </h3>
        <p className="text-sm leading-6">{tool.description || "No description"}</p>
      </div>

      <SchemaBlock title="Input Schema" schema={tool.inputSchema} />
      <SchemaBlock title="Output Schema" schema={tool.outputSchema} />
    </aside>
  );
}

function SchemaBlock({
  title,
  schema,
}: {
  title: string;
  schema: Record<string, string>;
}) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium uppercase text-muted-foreground">
        {title}
      </h3>
      <pre className="max-h-56 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs leading-5">
        {JSON.stringify(schema, null, 2)}
      </pre>
    </div>
  );
}
