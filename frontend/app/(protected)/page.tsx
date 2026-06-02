"use client";

import { Bot, Download, FileDown, Share2, ThumbsDown, ThumbsUp, User } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { ChatInput } from "../../components/ChatInput";
import { CopyButton, MarkdownMessage } from "../../components/MarkdownMessage";
import { exportAssistantAnswer, exportChatSession } from "../../lib/chat-export";
import {
  type ChatMessage,
  type Citation,
  type ChatFeedback,
  type ChatType,
  getSession,
  sendMessageFeedback,
  shareChatSession,
  streamChat,
} from "../../lib/chat";
import { useChatSessionsStore } from "../../lib/chat-store";
import { downloadKnowledgeFile } from "../../lib/knowledge-bases";
import { useKbStore } from "../../lib/kb-store";
import { useLlmInfo } from "../../lib/llm-info";

export default function ChatPage() {
  const router = useRouter();
  const params = useSearchParams();

  const sessions = useChatSessionsStore((s) => s.sessions);
  const loaded = useChatSessionsStore((s) => s.loaded);
  const refresh = useChatSessionsStore((s) => s.refresh);
  const newChat = useChatSessionsStore((s) => s.newChat);
  const bumpUpdatedAt = useChatSessionsStore((s) => s.bumpUpdatedAt);

  const sidParam = params.get("sid");
  const activeId = sidParam ? Number(sidParam) : null;
  const typeParam = params.get("t");
  const requestedChatType: ChatType = typeParam === "code" ? "code" : "general";

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeChatType, setActiveChatType] = useState<ChatType>(requestedChatType);
  const [streamingText, setStreamingText] = useState("");
  const [streamingCitations, setStreamingCitations] = useState<Citation[] | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);

  const knowledgeBases = useKbStore((s) => s.kbs);
  const kbsLoaded = useKbStore((s) => s.loaded);
  const refreshKbs = useKbStore((s) => s.refresh);
  const llmInfo = useLlmInfo();
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);

  const scrollToBottom = useCallback((force = false) => {
    if (!force && !shouldStickToBottomRef.current) return;
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      const target = messagesEndRef.current;
      if (target && typeof target.scrollIntoView === "function") {
        target.scrollIntoView({ behavior: "auto", block: "end" });
      } else if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      }
      scrollFrameRef.current = null;
    });
  }, []);

  useEffect(() => {
    if (!kbsLoaded) refreshKbs();
  }, [kbsLoaded, refreshKbs]);

  useEffect(() => {
    if (activeId !== null) return;
    if (!loaded) return;
    if (sessions.length === 0) return;
    const first = sessions[0];
    router.replace(`/?t=${first.chat_type}&sid=${first.id}`);
  }, [activeId, loaded, sessions, router]);

  useEffect(() => {
    if (activeId == null) {
      setMessages([]);
      setActiveChatType(requestedChatType);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await getSession(activeId);
        if (!cancelled) {
          setMessages(detail.messages);
          setActiveChatType(detail.chat_type);
          if (typeParam !== detail.chat_type) {
            router.replace(`/?t=${detail.chat_type}&sid=${detail.id}`);
          }
        }
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, requestedChatType, typeParam]);

  useEffect(() => {
    shouldStickToBottomRef.current = true;
    scrollToBottom(true);
  }, [activeId, scrollToBottom]);

  useEffect(() => {
    scrollToBottom(false);
  }, [messages, streamingText, isStreaming, scrollToBottom]);

  useEffect(() => {
    return () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    };
  }, []);

  const activeSessionTitle = activeId
    ? sessions.find((s) => s.id === activeId)?.title ?? "Chat"
    : "Chat";

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
        const session = await newChat(requestedChatType);
        sid = session.id;
        setActiveChatType(session.chat_type);
        router.replace(`/?t=${session.chat_type}&sid=${sid}`);
      }

      const optimisticUser: ChatMessage = {
        id: -Date.now(),
        role: "user",
        content: text,
        citations: null,
        created_at: new Date().toISOString(),
      };
      setMessages((current) => [...current, optimisticUser]);
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
          chat_type: activeChatType,
          ...(attachments.length ? { attachments } : {}),
        },
        {
          onToken: (token) => {
            collected += token;
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
            setMessages((current) => [...current, finalAssistant]);
            setStreamingText("");
            setStreamingCitations(null);
            setIsStreaming(false);
            bumpUpdatedAt(sid!);
            refresh();
          },
          onError: (message) => {
            setStreamError(message);
            setIsStreaming(false);
          },
        },
      );
    },
    [activeId, activeChatType, newChat, refresh, router, bumpUpdatedAt, requestedChatType],
  );

  const handleShareChat = useCallback(async () => {
    if (activeId == null) return;
    try {
      const share = await shareChatSession(activeId);
      const url = new URL(share.url_path, window.location.origin).toString();
      await copyText(url);
      setShareCopied(true);
      window.setTimeout(() => setShareCopied(false), 1500);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed to share chat");
    }
  }, [activeId, requestedChatType, typeParam]);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    shouldStickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 160;
  }, []);

  return (
    <section className="flex h-full flex-col bg-background">
      <header className="flex h-16 items-center justify-between border-b border-border bg-card/90 px-6 backdrop-blur">
        <div>
          <div className="text-base font-medium">{activeSessionTitle}</div>
          <div className="text-sm text-muted-foreground">
            {activeChatType === "code"
              ? "Programming AI workspace · t=code"
              : "Chat AI workspace · t=general"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleShareChat()}
            disabled={activeId == null || messages.length === 0}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Share2 className="h-4 w-4" />
            {shareCopied ? "Copied" : "Share"}
          </button>
          <button
            type="button"
            onClick={() =>
              exportChatSession({ title: activeSessionTitle, messages })
            }
            disabled={messages.length === 0}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <FileDown className="h-4 w-4" />
            Export chat
          </button>
          <div className="rounded-full border border-border bg-muted/50 px-4 py-2 text-sm text-muted-foreground">
            Model: {llmInfo?.label ?? "Loading"}
          </div>
        </div>
      </header>

      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="nice-scrollbar flex-1 overflow-auto px-6 py-7"
      >
        <div className="mx-auto max-w-6xl space-y-7">
          {messages.length === 0 && !isStreaming ? (
            <div className="py-16 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-card shadow-sm">
                <Bot className="h-5 w-5" />
              </div>
              <h1 className="mt-4 text-3xl font-semibold">How can I help?</h1>
              <p className="mx-auto mt-3 max-w-lg text-base text-muted-foreground">
                Ask a question, attach a file, or use a prompt chip below the
                composer. RAG can cite your selected databases.
              </p>
            </div>
          ) : null}

          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              sessionTitle={activeSessionTitle}
            />
          ))}

          {isStreaming ? (
            <MessageBubble
              message={{
                id: -1,
                role: "assistant",
                content: streamingText,
                citations: streamingCitations,
                created_at: new Date().toISOString(),
              }}
              sessionTitle={activeSessionTitle}
              streaming
            />
          ) : null}

          {streamError ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
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
        showDeepMode
        chatType={activeChatType}
      />
    </section>
  );
}

function MessageBubble({
  message,
  sessionTitle,
  streaming = false,
}: {
  message: ChatMessage;
  sessionTitle: string;
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  const ts = formatTimestamp(message.created_at);

  return (
    <div className={`flex items-start gap-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <Avatar isUser={isUser} />
      <div
        className={`flex min-w-0 max-w-[96%] flex-col gap-1 ${
          isUser ? "items-end" : "items-start"
        }`}
      >
        <div
          className={`min-w-0 max-w-full px-5 py-4 text-base leading-7 ${
            isUser
              ? "whitespace-pre-wrap rounded-2xl bg-foreground text-background shadow-sm [overflow-wrap:anywhere]"
              : "text-foreground"
          }`}
        >
          {isUser ? (
            <>
              {message.content}
              {streaming ? <span className="ml-1 animate-pulse">...</span> : null}
            </>
          ) : (
            <div className="min-w-0 max-w-full">
              <MarkdownMessage content={message.content || (streaming ? "Thinking..." : "")} />
              {streaming ? <span className="ml-1 animate-pulse">...</span> : null}
            </div>
          )}
          {message.citations && message.citations.length > 0 ? (
            <CitationList citations={message.citations} />
          ) : null}
        </div>
        <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
          <span>{ts}</span>
          {!isUser && !streaming && message.content ? (
            <>
              <CopyButton text={message.content} label="Copy" />
              <IconAction
                label="Export answer"
                onClick={() =>
                  exportAssistantAnswer(
                    message,
                    `${sessionTitle}-answer-${message.id}`,
                  )
                }
              >
                <Share2 className="h-4 w-4" />
                Export
              </IconAction>
              <MessageFeedbackActions message={message} />
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  async function handleDownload(citation: Citation) {
    try {
      await downloadKnowledgeFile(citation.file_id, citation.filename);
    } catch (err) {
      window.alert(
        err instanceof Error ? err.message : "Failed to download source",
      );
    }
  }

  return (
    <div className="mt-3 border-t border-border/60 pt-2 text-sm text-muted-foreground">
      <span>Sources:</span>
      <div className="mt-2 flex flex-wrap gap-2">
        {citations.map((citation, index) => (
          <span
            key={`${citation.file_id}:${index}`}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1"
          >
            <span>{citation.filename}</span>
            <button
              type="button"
              onClick={() => void handleDownload(citation)}
              aria-label={`Download ${citation.filename}`}
              title={`Download ${citation.filename}`}
              className="rounded p-0.5 hover:bg-muted hover:text-foreground"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}

function MessageFeedbackActions({ message }: { message: ChatMessage }) {
  const [selected, setSelected] = useState<ChatFeedback | null>(null);
  const [sending, setSending] = useState(false);
  const disabled = sending || message.id <= 0;

  async function vote(feedback: ChatFeedback) {
    if (disabled) return;
    setSending(true);
    try {
      await sendMessageFeedback(message.id, feedback);
      setSelected(feedback);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={() => void vote("like")}
        disabled={disabled}
        aria-label="Like response"
        title="Like response"
        className={`inline-flex items-center rounded-md px-2 py-1 hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 ${
          selected === "like" ? "text-green-600" : ""
        }`}
      >
        <ThumbsUp className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => void vote("dislike")}
        disabled={disabled}
        aria-label="Dislike response"
        title="Dislike response"
        className={`inline-flex items-center rounded-md px-2 py-1 hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 ${
          selected === "dislike" ? "text-red-600" : ""
        }`}
      >
        <ThumbsDown className="h-4 w-4" />
      </button>
    </div>
  );
}

function IconAction({
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
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-muted hover:text-foreground"
    >
      {children}
    </button>
  );
}

function Avatar({ isUser }: { isUser: boolean }) {
  return isUser ? (
    <div
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-foreground text-background"
      aria-label="User"
    >
      <User className="h-5 w-5" />
    </div>
  ) : (
    <div
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-border bg-card text-foreground"
      aria-label="Assistant"
    >
      <Bot className="h-5 w-5" />
    </div>
  );
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const time = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  if (sameDay) return time;
  return `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
}

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
    return;
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(textarea);
    }
  }
}
