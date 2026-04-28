"use client";

import { Bot, Check, Copy, User } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ChatInput } from "./ChatInput";
import { useChatSessionsStore } from "../lib/chat-store";
import {
  type ChatMessage,
  type Citation,
  getSession,
  streamChat,
} from "../lib/chat";
import { useKbStore } from "../lib/kb-store";
import { useLlmInfo } from "../lib/llm-info";

export function ChatWorkspace({
  routeBase,
  pageTitle,
}: {
  routeBase: string;
  pageTitle: string;
}) {
  const router = useRouter();
  const params = useSearchParams();

  const sessions = useChatSessionsStore((s) => s.sessions);
  const loaded = useChatSessionsStore((s) => s.loaded);
  const refresh = useChatSessionsStore((s) => s.refresh);
  const newChat = useChatSessionsStore((s) => s.newChat);
  const bumpUpdatedAt = useChatSessionsStore((s) => s.bumpUpdatedAt);

  const sidParam = params.get("sid");
  const activeId = sidParam ? Number(sidParam) : null;

  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const knowledgeBases = useKbStore((s) => s.kbs);
  const kbsLoaded = useKbStore((s) => s.loaded);
  const refreshKbs = useKbStore((s) => s.refresh);
  const llmInfo = useLlmInfo();

  const [streamingText, setStreamingText] = useState("");
  const [streamingCitations, setStreamingCitations] = useState<Citation[] | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!kbsLoaded) refreshKbs();
  }, [kbsLoaded, refreshKbs]);

  useEffect(() => {
    if (activeId !== null) return;
    if (!loaded) return;
    if (sessions.length === 0) return;
    router.replace(`${routeBase}?sid=${sessions[0].id}`);
  }, [activeId, loaded, sessions, router, routeBase]);

  useEffect(() => {
    if (activeId == null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await getSession(activeId);
        if (cancelled) return;
        setMessages(detail.messages);
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, isStreaming]);

  const activeSessionTitle = activeId
    ? sessions.find((s) => s.id === activeId)?.title ?? pageTitle
    : pageTitle;

  const handleSend = useCallback(
    async (text: string, useRag: boolean, kbIds: number[] | null) => {
      let sid = activeId;
      if (sid == null) {
        const s = await newChat();
        sid = s.id;
        router.replace(`${routeBase}?sid=${sid}`);
      }
      const optimisticUser: ChatMessage = {
        id: -Date.now(),
        role: "user",
        content: text,
        citations: null,
        created_at: new Date().toISOString(),
      };
      setMessages((cur) => [...cur, optimisticUser]);
      setStreamingText("");
      setStreamingCitations(null);
      setStreamError(null);
      setIsStreaming(true);

      let collected = "";
      let collectedCitations: Citation[] = [];

      await streamChat(
        { session_id: sid, message: text, use_rag: useRag, kb_ids: kbIds },
        {
          onToken: (t) => {
            collected += t;
            setStreamingText(collected);
          },
          onCitations: (items) => {
            collectedCitations = items;
            setStreamingCitations(items);
          },
          onDone: () => {
            const finalAssistant: ChatMessage = {
              id: -Date.now() - 1,
              role: "assistant",
              content: collected,
              citations: collectedCitations.length ? collectedCitations : null,
              created_at: new Date().toISOString(),
            };
            setMessages((cur) => [...cur, finalAssistant]);
            setStreamingText("");
            setStreamingCitations(null);
            setIsStreaming(false);
            bumpUpdatedAt(sid!);
            refresh();
          },
          onError: (msg) => {
            setStreamError(msg);
            setIsStreaming(false);
          },
        },
      );
    },
    [activeId, newChat, refresh, router, bumpUpdatedAt, routeBase],
  );

  return (
    <section className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <header className="flex h-14 items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4">
        <div className="text-sm font-medium">{activeSessionTitle}</div>
        <div className="text-xs text-zinc-400">
          Model: {llmInfo?.label ?? "…"}
        </div>
      </header>

      <div className="flex-1 overflow-auto px-4 py-6">
        <div className="mx-auto max-w-5xl space-y-4">
          {messages.length === 0 && !isStreaming ? (
            <div className="rounded-lg border border-dashed border-zinc-700 bg-zinc-900 p-10 text-center text-sm text-zinc-400">
              Type a message below to start. Toggle "Use RAG" to ground the
              answer in your knowledge bases.
            </div>
          ) : null}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {isStreaming ? (
            <MessageBubble
              message={{
                id: -1,
                role: "assistant",
                content: streamingText || "…",
                citations: streamingCitations,
                created_at: new Date().toISOString(),
              }}
              streaming
            />
          ) : null}
          {streamError ? (
            <div className="rounded-md border border-red-500/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
              Stream error: {streamError}
            </div>
          ) : null}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <ChatInput
        knowledgeBases={knowledgeBases}
        disabled={isStreaming}
        onSend={handleSend}
      />
    </section>
  );
}

function MessageBubble({
  message,
  streaming = false,
}: {
  message: ChatMessage;
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  const ts = formatTimestamp(message.created_at);
  return (
    <div
      className={`flex items-start gap-2 ${
        isUser ? "flex-row-reverse" : "flex-row"
      }`}
    >
      <Avatar isUser={isUser} />
      <div
        className={`flex max-w-[85%] flex-col gap-1 md:max-w-[75%] lg:max-w-[65%] ${
          isUser ? "items-end" : "items-start"
        }`}
      >
        <div
          className={`rounded-lg px-3 py-2 text-sm ${
            isUser
              ? "whitespace-pre-wrap bg-zinc-700 text-zinc-100"
              : "border border-zinc-700 bg-zinc-900 text-zinc-100"
          }`}
        >
          {isUser ? (
            <>
              {message.content}
              {streaming ? <span className="ml-1 animate-pulse">▍</span> : null}
            </>
          ) : (
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content || (streaming ? "…" : "")}
              </ReactMarkdown>
              {streaming ? <span className="ml-1 animate-pulse">▍</span> : null}
            </div>
          )}
          {message.citations && message.citations.length > 0 ? (
            <div className="mt-2 border-t border-zinc-700 pt-2 text-xs text-zinc-400">
              Sources:{" "}
              {message.citations.map((c, i) => (
                <span key={c.file_id}>
                  {i > 0 ? ", " : ""}
                  {c.filename}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-2 px-1 text-[10px] text-zinc-500">
          <span>{ts}</span>
          {!isUser && !streaming && message.content ? (
            <CopyButton text={message.content} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
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
      onClick={handleCopy}
      aria-label="Copy markdown"
      className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-zinc-800 hover:text-zinc-100"
    >
      {copied ? (
        <>
          <Check className="h-3 w-3" /> Copied
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" /> Copy
        </>
      )}
    </button>
  );
}

function Avatar({ isUser }: { isUser: boolean }) {
  return isUser ? (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-700 text-zinc-100"
      aria-label="User"
    >
      <User className="h-4 w-4" />
    </div>
  ) : (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-zinc-700 bg-zinc-900 text-zinc-100"
      aria-label="Assistant"
    >
      <Bot className="h-4 w-4" />
    </div>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const time = d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  if (sameDay) return time;
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${date}, ${time}`;
}
