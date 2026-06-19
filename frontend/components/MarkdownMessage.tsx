"use client";

import { Check, Copy, Download } from "lucide-react";
import { useRef, useState, type ComponentType, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import * as SyntaxHighlighterModule from "react-syntax-highlighter/dist/esm/light";
import * as bashModule from "react-syntax-highlighter/dist/esm/languages/hljs/bash";
import * as cssModule from "react-syntax-highlighter/dist/esm/languages/hljs/css";
import * as javascriptModule from "react-syntax-highlighter/dist/esm/languages/hljs/javascript";
import * as jsonModule from "react-syntax-highlighter/dist/esm/languages/hljs/json";
import * as markdownModule from "react-syntax-highlighter/dist/esm/languages/hljs/markdown";
import * as pythonModule from "react-syntax-highlighter/dist/esm/languages/hljs/python";
import * as sqlModule from "react-syntax-highlighter/dist/esm/languages/hljs/sql";
import * as typescriptModule from "react-syntax-highlighter/dist/esm/languages/hljs/typescript";
import * as xmlModule from "react-syntax-highlighter/dist/esm/languages/hljs/xml";
import { vs2015 } from "react-syntax-highlighter/dist/esm/styles/hljs";
import remarkGfm from "remark-gfm";

import { downloadBlob } from "../lib/download";

type SyntaxHighlighterComponent = ComponentType<any> & {
  registerLanguage?: (name: string, language: unknown) => void;
};

function unwrapDefault<T>(module: T): T extends { default: infer U } ? U : T {
  return ((module as { default?: unknown }).default ?? module) as T extends {
    default: infer U;
  }
    ? U
    : T;
}

const syntaxHighlighter = unwrapDefault(SyntaxHighlighterModule);
const canSyntaxHighlight = typeof syntaxHighlighter === "function";
const SyntaxHighlighter = syntaxHighlighter as SyntaxHighlighterComponent;
const bash = unwrapDefault(bashModule);
const css = unwrapDefault(cssModule);
const javascript = unwrapDefault(javascriptModule);
const json = unwrapDefault(jsonModule);
const markdown = unwrapDefault(markdownModule);
const python = unwrapDefault(pythonModule);
const sql = unwrapDefault(sqlModule);
const typescript = unwrapDefault(typescriptModule);
const xml = unwrapDefault(xmlModule);

const languages = [
  ["bash", bash],
  ["css", css],
  ["javascript", javascript],
  ["js", javascript],
  ["json", json],
  ["markdown", markdown],
  ["md", markdown],
  ["python", python],
  ["py", python],
  ["sql", sql],
  ["typescript", typescript],
  ["ts", typescript],
  ["xml", xml],
  ["html", xml],
] as const;

if (typeof SyntaxHighlighter.registerLanguage === "function") {
  for (const [name, languageDefinition] of languages) {
    SyntaxHighlighter.registerLanguage(name, languageDefinition);
  }
}

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ code: CodeBlock, pre: PreBlock, table: TableBlock }}
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

  if (!language && !looksLikeCode(text)) {
    return (
      <div className="my-3 max-w-full whitespace-pre-wrap rounded-lg border border-border bg-muted/50 px-4 py-3 text-sm leading-6 text-foreground [overflow-wrap:anywhere]">
        {text}
      </div>
    );
  }

  return (
    <div className="my-4 max-w-full overflow-hidden rounded-xl border border-[#3c3c3c] bg-[#1e1e1e] text-[#d4d4d4] shadow-sm">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5 text-sm text-slate-300">
        <span>{language ?? "code"}</span>
        <CopyButton text={text} label="Copy code" />
      </div>
      {canSyntaxHighlight ? (
        <SyntaxHighlighter
          language={language ?? "text"}
          style={vs2015}
          PreTag="div"
          customStyle={{
            margin: 0,
            padding: "1rem",
            background: "#1e1e1e",
            overflowX: "auto",
            fontSize: "0.875rem",
            lineHeight: "1.5rem",
          }}
          codeTagProps={{ className: "chat-code-token" }}
          {...rest}
        >
          {text}
        </SyntaxHighlighter>
      ) : (
        <pre className="m-0 overflow-x-auto bg-[#1e1e1e] p-4 text-sm leading-6">
          <code className="chat-code-token">{text}</code>
        </pre>
      )}
    </div>
  );
}

function PreBlock({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}

function looksLikeCode(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (/^(\$|>|PS\s+[A-Z]:\\|[A-Z]:\\.*>)/m.test(trimmed)) return true;
  if (/[{};]|=>|<\/?[a-z][\s\S]*>/i.test(trimmed)) return true;
  if (
    /^\s*(import|from|export|const|let|var|function|class|def|return|if|for|while|try|catch|SELECT|INSERT|UPDATE|DELETE|CREATE|npm|pnpm|yarn|git|docker|python|pip|curl)\b/im.test(
      trimmed,
    )
  ) {
    return true;
  }

  const codeishLines = trimmed
    .split("\n")
    .filter((line) => /^\s{2,}\S/.test(line) && /[()[\]{}=<>:]/.test(line));
  return codeishLines.length >= 2;
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
