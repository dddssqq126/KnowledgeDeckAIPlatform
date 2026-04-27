"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = {
  content: string;
};

function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = code;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      } finally {
        document.body.removeChild(ta);
      }
    }
  }

  return (
    <button
      type="button"
      onClick={copyCode}
      className="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] hover:bg-white/10"
      aria-label="Copy code"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy code"}
    </button>
  );
}

export function MarkdownWithCodeCopy({ content }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }: any) {
          const inline = Boolean((props as { inline?: boolean }).inline);
          const raw = String(children).replace(/\n$/, "");
          if (inline) {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          }
          const lang = /language-(\w+)/.exec(className || "")?.[1] ?? "text";
          return (
            <div className="my-2 overflow-hidden rounded-md border border-border bg-muted">
              <div className="flex items-center justify-between border-b border-border px-2 py-1 text-[11px] text-muted-foreground">
                <span>{lang}</span>
                <CopyCodeButton code={raw} />
              </div>
              <pre className="m-0 overflow-x-auto bg-transparent p-3 text-xs leading-relaxed">
                <code className={className}>{raw}</code>
              </pre>
            </div>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
