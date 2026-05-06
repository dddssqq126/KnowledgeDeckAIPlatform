"use client";

import { Check, Copy, Download } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { downloadBlob } from "../lib/download";

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ code: CodeBlock, table: TableBlock }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function CodeBlock(props: any) {
  const { inline, className, children, ...rest } = props;
  const text = String(children ?? "").replace(/\n$/, "");
  const language = /language-(\w+)/.exec(className || "")?.[1];

  if (inline) {
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  }

  return (
    <div className="my-4 overflow-hidden rounded-xl border border-border bg-slate-950 text-slate-100 shadow-sm">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5 text-sm text-slate-300">
        <span>{language ?? "code"}</span>
        <CopyButton text={text} label="Copy code" />
      </div>
      <pre className="chat-code-pre overflow-x-auto p-4 text-sm leading-6">
        <code className={className} {...rest}>
          {children}
        </code>
      </pre>
    </div>
  );
}

function TableBlock({ children }: { children?: ReactNode }) {
  const tableRef = useRef<HTMLTableElement | null>(null);

  function tableText() {
    const rows = Array.from(tableRef.current?.rows ?? []);
    return rows
      .map((row) =>
        Array.from(row.cells)
          .map((cell) => (cell.innerText ?? cell.textContent ?? "").trim())
          .join("\t"),
      )
      .join("\n");
  }

  function downloadExcel() {
    const table = tableRef.current;
    if (!table) return;
    const workbook = tableToSpreadsheetXml(table);
    downloadBlob(
      new Blob([workbook], { type: "application/vnd.ms-excel;charset=utf-8" }),
      "table-export.xls",
    );
  }

  return (
    <div className="my-4 overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="flex items-center justify-between border-b border-border bg-muted px-4 py-2.5 text-sm text-muted-foreground">
        <span>Table</span>
        <div className="flex items-center gap-1">
          <IconButton onClick={downloadExcel} label="Download Excel">
            <Download className="h-4 w-4" />
          </IconButton>
          <CopyButton text={tableText} label="Copy table" />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table ref={tableRef}>{children}</table>
      </div>
    </div>
  );
}

function tableToSpreadsheetXml(table: HTMLTableElement): string {
  const rows = Array.from(table.rows)
    .map((row) => {
      const cells = Array.from(row.cells)
        .map((cell) => {
          const text = escapeXml((cell.innerText ?? cell.textContent ?? "").trim());
          return `<Cell><Data ss:Type="String">${text}</Data></Cell>`;
        })
        .join("");
      return `<Row>${cells}</Row>`;
    })
    .join("");

  return `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:x="urn:schemas-microsoft-com:office:excel"
  xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  <Worksheet ss:Name="Table">
    <Table>${rows}</Table>
  </Worksheet>
</Workbook>`;
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function IconButton({
  children,
  label,
  onClick,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-background hover:text-foreground"
    >
      {children}
    </button>
  );
}

export function CopyButton({
  text,
  label,
}: {
  text: string | (() => string);
  label: string;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const value = typeof text === "function" ? text() : text;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand("copy");
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      } finally {
        document.body.removeChild(textarea);
      }
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={label}
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-background hover:text-foreground"
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {copied ? "Copied" : label}
    </button>
  );
}
