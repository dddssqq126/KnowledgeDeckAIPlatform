"use client";

import {
  Bot,
  Check,
  Copy,
  Download,
  FileText,
  MessageSquare,
  ThumbsDown,
  ThumbsUp,
  User,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ChatInput } from "./ChatInput";
import { CitationList } from "./CitationList";
import { useChatSessionsStore } from "../lib/chat-store";
import {
  type ChatMessage,
  type ChatAttachment,
  type Citation,
  type ChatFeedback,
  downloadChatAttachment,
  getSession,
  sendMessageFeedback,
  streamChat,
} from "../lib/chat";
import { downloadBlob, safeFilename } from "../lib/download";
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
  const [streamingCitations, setStreamingCitations] = useState<
    Citation[] | null
  >(null);
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
    ? (sessions.find((s) => s.id === activeId)?.title ?? pageTitle)
    : pageTitle;

  const handleSend = useCallback(
    async (
      text: string,
      useRag: boolean,
      kbIds: number[] | null,
      deepMode: boolean,
      attachments: File[] = [],
    ) => {
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
        attachments: attachments.map((file, index) => ({
          id: -Date.now() - index - 10,
          filename: file.name,
          extension: file.name.includes(".")
            ? (file.name.split(".").pop() ?? "")
            : "",
          size_bytes: file.size,
          created_at: new Date().toISOString(),
        })),
      };
      setMessages((cur) => [...cur, optimisticUser]);
      setStreamingText("");
      setStreamingCitations(null);
      setStreamError(null);
      setIsStreaming(true);

      let collected = "";
      let collectedCitations: Citation[] = [];

      await streamChat(
        {
          session_id: sid,
          message: text,
          use_rag: useRag,
          kb_ids: kbIds,
          deep_mode: deepMode,
          ...(attachments.length ? { attachments } : {}),
        },
        {
          onToken: (t) => {
            collected += t;
            setStreamingText(collected);
          },
          onCitations: (items) => {
            collectedCitations = items;
            setStreamingCitations(items);
          },
          onDone: (data) => {
            const finalAssistant: ChatMessage = {
              id: data?.message_id ?? -Date.now() - 1,
              role: "assistant",
              content: collected,
              citations: collectedCitations.length ? collectedCitations : null,
              created_at: new Date().toISOString(),
            };
            setMessages((cur) => [...cur, finalAssistant]);
            void getSession(sid!).then((detail) =>
              setMessages(detail.messages),
            );
            setStreamingText("");
            setStreamingCitations(null);
            setIsStreaming(false);
            bumpUpdatedAt(sid!);
            refresh();
          },
          onError: (msg) => {
            setStreamError(msg);
            setIsStreaming(false);
            void getSession(sid!).then((detail) =>
              setMessages(detail.messages),
            );
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
              {message.content ? message.content : null}
              <AttachmentList attachments={message.attachments ?? []} />
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
          {message.citations ? (
            <CitationList citations={message.citations} />
          ) : null}
        </div>
        <div className="flex items-center gap-2 px-1 text-[10px] text-zinc-500">
          <span>{ts}</span>
          {!isUser && !streaming && message.content ? (
            <MessageActions message={message} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function AttachmentList({ attachments }: { attachments: ChatAttachment[] }) {
  if (attachments.length === 0) return null;

  async function handleDownload(attachment: ChatAttachment) {
    if (attachment.id <= 0) return;
    const blob = await downloadChatAttachment(attachment.id);
    downloadBlob(
      blob,
      safeFilename(attachment.filename, `attachment-${attachment.id}`),
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-1">
      {attachments.map((attachment) => (
        <button
          key={`${attachment.id}-${attachment.filename}`}
          type="button"
          onClick={() => handleDownload(attachment)}
          disabled={attachment.id <= 0}
          className="flex max-w-sm items-center justify-between gap-3 rounded-md border border-zinc-600 bg-zinc-800/70 px-2 py-1.5 text-left text-xs text-zinc-100 hover:bg-zinc-800 disabled:cursor-default disabled:opacity-70"
          title={attachment.id <= 0 ? "上傳後即可下載" : "下載附件"}
        >
          <span className="flex min-w-0 items-center gap-2">
            <FileText className="h-3.5 w-3.5 shrink-0 text-zinc-300" />
            <span className="truncate">{attachment.filename}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 text-zinc-400">
            {formatBytes(attachment.size_bytes)}
            <Download className="h-3.5 w-3.5" />
          </span>
        </button>
      ))}
    </div>
  );
}

function MessageActions({ message }: { message: ChatMessage }) {
  const [selected, setSelected] = useState<ChatFeedback | null>(null);
  const [comment, setComment] = useState("");
  const [commentOpen, setCommentOpen] = useState(false);
  const [sending, setSending] = useState(false);

  async function vote(feedback: ChatFeedback) {
    if (sending || message.id <= 0) return;
    setSending(true);
    try {
      await sendMessageFeedback(message.id, feedback, comment);
      setSelected(feedback);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex items-center gap-1">
      <CopyButton text={message.content} />
      <button
        type="button"
        onClick={() => vote("like")}
        disabled={sending || message.id <= 0}
        aria-label="Like response"
        className={`rounded px-1 py-0.5 hover:bg-zinc-800 hover:text-zinc-100 ${
          selected === "like" ? "text-green-400" : ""
        }`}
      >
        <ThumbsUp className="h-3 w-3" />
      </button>
      <button
        type="button"
        onClick={() => vote("dislike")}
        disabled={sending || message.id <= 0}
        aria-label="Dislike response"
        className={`rounded px-1 py-0.5 hover:bg-zinc-800 hover:text-zinc-100 ${
          selected === "dislike" ? "text-red-400" : ""
        }`}
      >
        <ThumbsDown className="h-3 w-3" />
      </button>
      <button
        type="button"
        onClick={() => setCommentOpen((open) => !open)}
        disabled={message.id <= 0}
        aria-label="Add feedback comment"
        className={`rounded px-1 py-0.5 hover:bg-zinc-800 hover:text-zinc-100 ${
          commentOpen || comment.trim() ? "text-sky-300" : ""
        }`}
      >
        <MessageSquare className="h-3 w-3" />
      </button>
      {commentOpen ? (
        <form
          className="ml-1 flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            vote(selected ?? "like");
          }}
        >
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="輸入回覆"
            maxLength={2000}
            className="w-40 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[11px] text-zinc-100 outline-none placeholder:text-zinc-500 focus:border-zinc-500"
          />
          <button
            type="submit"
            disabled={sending || message.id <= 0}
            className="rounded bg-zinc-800 px-2 py-1 text-[11px] text-zinc-200 hover:bg-zinc-700 disabled:opacity-40"
          >
            送出
          </button>
        </form>
      ) : null}
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
  const date = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  return `${date}, ${time}`;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}
