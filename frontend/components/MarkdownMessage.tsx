"use client";

import { Check, Copy, Download } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import SyntaxHighlighter from "react-syntax-highlighter/dist/esm/light";
import bash from "react-syntax-highlighter/dist/esm/languages/hljs/bash";
import css from "react-syntax-highlighter/dist/esm/languages/hljs/css";
import javascript from "react-syntax-highlighter/dist/esm/languages/hljs/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/hljs/json";
import markdown from "react-syntax-highlighter/dist/esm/languages/hljs/markdown";
import python from "react-syntax-highlighter/dist/esm/languages/hljs/python";
import sql from "react-syntax-highlighter/dist/esm/languages/hljs/sql";
import typescript from "react-syntax-highlighter/dist/esm/languages/hljs/typescript";
import xml from "react-syntax-highlighter/dist/esm/languages/hljs/xml";
import { vs2015 } from "react-syntax-highlighter/dist/esm/styles/hljs";
import remarkGfm from "remark-gfm";

import { downloadBlob } from "../lib/download";

SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("css", css);
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("js", javascript);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("markdown", markdown);
SyntaxHighlighter.registerLanguage("md", markdown);
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("py", python);
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("ts", typescript);
SyntaxHighlighter.registerLanguage("xml", xml);
SyntaxHighlighter.registerLanguage("html", xml);

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

// react-markdown v9 no longer passes an `inline` prop to the `code` renderer,
// and block (fenced/indented) code always arrives wrapped in a `<pre>` handled
// by PreBlock. So the `code` renderer is only for INLINE code — it must emit an
// inline <code>; a <div> here would be invalid inside a <p> (hydration error).
function CodeBlock(props: any) {
  const { className, children, ...rest } = props;
  return (
    <code className={className} {...rest}>
      {children}
    </code>
  );
}

// Block-level code. Markdown renders fenced/indented blocks as <pre><code>, so
// they reach us here at block level (never inside a <p>) — a <div> is safe.
// We read the inner <code> element's class + text rather than the removed
// `inline` prop.
function PreBlock({ children }: { children?: ReactNode }) {
  const codeEl: any = Array.isArray(children) ? children[0] : children;
  const codeProps = codeEl?.props ?? {};
  const className: string = codeProps.className ?? "";
  const text = String(codeProps.children ?? "").replace(/\n$/, "");
  const language = /language-(\w+)/.exec(className)?.[1];

  if (!text) {
    return <pre>{children}</pre>;
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
      >
        {text}
      </SyntaxHighlighter>
    </div>
  );
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
