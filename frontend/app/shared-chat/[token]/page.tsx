"use client";

import { Bot, User } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthGuard } from "../../../components/AuthGuard";
import { MarkdownMessage } from "../../../components/MarkdownMessage";
import { type ChatMessage, type SessionDetail, getSharedChat } from "../../../lib/chat";

export default function SharedChatPage() {
  return (
    <AuthGuard>
      <SharedChatContent />
    </AuthGuard>
  );
}

function SharedChatContent() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const detail = await getSharedChat(token);
        if (!cancelled) setSession(detail);
      } catch {
        if (!cancelled) setError("Shared chat not found or no longer available.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card/90 px-6 py-5 backdrop-blur">
        <div className="mx-auto max-w-6xl">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Shared conversation
          </div>
          <h1 className="mt-1 text-2xl font-semibold">
            {session?.title ?? "Loading shared chat"}
          </h1>
          {session ? (
            <div className="mt-1 text-sm text-muted-foreground">
              Updated {formatTimestamp(session.updated_at)}
            </div>
          ) : null}
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-6 py-7">
        {error ? (
          <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
            {error}
          </div>
        ) : null}
        {!session && !error ? (
          <div className="text-sm text-muted-foreground">Loading conversation...</div>
        ) : null}
        {session ? (
          <div className="space-y-7">
            {session.messages.map((message) => (
              <SharedMessage key={message.id} message={message} />
            ))}
          </div>
        ) : null}
      </div>
    </main>
  );
}

function SharedMessage({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex items-start gap-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
          isUser
            ? "bg-foreground text-background"
            : "border border-border bg-card text-foreground"
        }`}
        aria-label={isUser ? "User" : "Assistant"}
      >
        {isUser ? <User className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
      </div>
      <div className={`min-w-0 max-w-[96%] ${isUser ? "text-right" : "text-left"}`}>
        <div
          className={`min-w-0 max-w-full px-5 py-4 text-base leading-7 ${
            isUser
              ? "whitespace-pre-wrap rounded-2xl bg-foreground text-background shadow-sm [overflow-wrap:anywhere]"
              : "text-foreground"
          }`}
        >
          {isUser ? message.content : <MarkdownMessage content={message.content} />}
          {!isUser && message.citations?.length ? (
            <div className="mt-3 border-t border-border/60 pt-2 text-sm text-muted-foreground">
              <span>Sources:</span>
              <div className="mt-2 flex flex-wrap gap-2">
                {message.citations.map((citation, index) => (
                  <span
                    key={`${citation.file_id}:${index}`}
                    className="rounded-md border border-border bg-background px-2 py-1"
                  >
                    {citation.filename}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        <div className="mt-1 px-1 text-xs text-muted-foreground">
          {formatTimestamp(message.created_at)}
        </div>
      </div>
    </div>
  );
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
