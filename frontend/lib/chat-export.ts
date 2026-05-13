"use client";

import { type ChatMessage, type Citation } from "./chat";
import { downloadTextFile, safeFilename } from "./download";

type ChatExportInput = {
  title: string;
  messages: ChatMessage[];
};

export function exportChatSession({ title, messages }: ChatExportInput): void {
  const filename = `${safeFilename(title, "chat")}.md`;
  downloadTextFile(formatChatSessionMarkdown({ title, messages }), filename);
}

export function exportAssistantAnswer(
  message: ChatMessage,
  title = "assistant-answer",
): void {
  const filename = `${safeFilename(title, "assistant-answer")}.md`;
  downloadTextFile(formatAnswerMarkdown(message), filename);
}

export function formatChatSessionMarkdown({ title, messages }: ChatExportInput): string {
  const lines = [`# ${title || "Chat"}`, "", `Exported: ${new Date().toISOString()}`, ""];

  for (const message of messages) {
    const heading = message.role === "user" ? "User" : "Assistant";
    lines.push(`## ${heading}`);
    lines.push("");
    lines.push(`Time: ${message.created_at}`);
    lines.push("");
    lines.push(message.content || "");
    appendCitations(lines, message.citations);
    lines.push("");
  }

  return `${lines.join("\n").trim()}\n`;
}

export function formatAnswerMarkdown(message: ChatMessage): string {
  const lines = ["# Assistant Answer", "", `Time: ${message.created_at}`, "", message.content || ""];
  appendCitations(lines, message.citations);
  return `${lines.join("\n").trim()}\n`;
}

function appendCitations(lines: string[], citations: Citation[] | null): void {
  if (!citations?.length) return;
  lines.push("");
  lines.push("## Sources");
  lines.push("");
  for (const citation of citations) {
    lines.push(`- ${citation.filename}`);
  }
}
