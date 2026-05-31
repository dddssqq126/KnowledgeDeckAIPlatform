"use client";

import {
  Bot,
  Download,
  FileDown,
  Share2,
  ThumbsDown,
  ThumbsUp,
  User,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ChatInput } from "../../components/ChatInput";
import { CopyButton, MarkdownMessage } from "../../components/MarkdownMessage";
import {
  exportAssistantAnswer,
  exportChatSession,
} from "../../lib/chat-export";
import {
  type ChatMessage,
  type Citation,
  type ChatFeedback,
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

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [streamingCitations, setStreamingCitations] = useState<
    Citation[] | null
  >(null);
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
        scrollContainerRef.current.scrollTop =
          scrollContainerRef.current.scrollHeight;
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
    router.replace(`/?sid=${sessions[0].id}`);
  }, [activeId, loaded, sessions, router]);

  useEffect(() => {
    if (activeId == null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await getSession(activeId);
        if (!cancelled) setMessages(detail.messages);
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

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
    ? (sessions.find((s) => s.id === activeId)?.title ?? "Chat")
    : "Chat";

  const handleSend = useCallback(
    async (
      text: string,
      useRag: boolean,
      kbIds: number[] | null,
      deepMode: boolean,
    ) => {
      let sid = activeId;
      if (sid == null) {
        const session = await newChat();
        sid = session.id;
        router.replace(`/?sid=${sid}`);
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
    [activeId, newChat, refresh, router, bumpUpdatedAt],
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
  }, [activeId]);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    shouldStickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 160;
  }, []);

  return (
    <section className="relative flex h-full flex-col overflow-hidden bg-[#f8fafd] text-slate-950">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-24 top-10 h-72 w-72 rounded-full bg-[#d7e3ff]/70 blur-3xl" />
        <div className="absolute right-10 top-16 h-64 w-64 rounded-full bg-[#d7f6e5]/70 blur-3xl" />
        <div className="absolute bottom-12 left-1/3 h-72 w-72 rounded-full bg-[#fde7f3]/60 blur-3xl" />
      </div>
      <header className="relative z-10 flex min-h-20 items-center justify-between border-b border-white/70 bg-white/75 px-6 shadow-[0_8px_30px_rgba(60,64,67,0.08)] backdrop-blur-2xl">
        <div className="min-w-0">
          <div className="truncate text-lg font-semibold tracking-tight text-slate-900">
            {activeSessionTitle}
          </div>
          <div className="mt-1 flex items-center gap-2 text-sm text-slate-500">
            <span className="h-2 w-2 rounded-full bg-gradient-to-r from-[#4285f4] via-[#34a853] to-[#fbbc04]" />
            Gemini-inspired RAG workspace
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => void handleShareChat()}
            disabled={activeId == null || messages.length === 0}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/80 px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:border-[#4285f4]/40 hover:bg-white hover:text-[#1a73e8] hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
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
            className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/80 px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:border-[#34a853]/40 hover:bg-white hover:text-[#188038] hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
          >
            <FileDown className="h-4 w-4" />
            Export chat
          </button>
          <div className="rounded-full border border-white/80 bg-gradient-to-r from-[#e8f0fe] via-white to-[#e6f4ea] px-4 py-2 text-sm font-medium text-slate-600 shadow-sm">
            Model:{" "}
            <span className="text-slate-900">
              {llmInfo?.label ?? "Loading"}
            </span>
          </div>
        </div>
      </header>

      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="nice-scrollbar relative z-10 flex-1 overflow-auto px-6 py-8"
      >
        <div className="mx-auto max-w-6xl space-y-7">
          {messages.length === 0 && !isStreaming ? (
            <div className="py-16 text-center">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl bg-gradient-to-br from-[#4285f4] via-[#a142f4] to-[#fbbc04] p-[2px] shadow-[0_18px_50px_rgba(66,133,244,0.24)]">
                <div className="flex h-full w-full items-center justify-center rounded-[1.35rem] bg-white/90">
                  <Bot className="h-7 w-7 text-[#1a73e8]" />
                </div>
              </div>
              <h1 className="mt-6 bg-gradient-to-r from-[#4285f4] via-[#a142f4] to-[#ea4335] bg-clip-text text-4xl font-semibold tracking-tight text-transparent">
                How can I help?
              </h1>
              <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-slate-500">
                Ask a question, attach a file, or use RAG with selected
                databases. Answers keep citations close while the interface
                stays calm and Gemini-like.
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

      <div className="relative z-20">
        <ChatInput
          knowledgeBases={knowledgeBases}
          disabled={isStreaming}
          onSend={handleSend}
          showDeepMode
        />
      </div>
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
    <div
      className={`flex items-start gap-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      <Avatar isUser={isUser} />
      <div
        className={`flex min-w-0 max-w-[96%] flex-col gap-2 ${
          isUser ? "items-end" : "items-start"
        }`}
      >
        <div
          className={`min-w-0 max-w-full px-5 py-4 text-base leading-7 shadow-sm ${
            isUser
              ? "whitespace-pre-wrap rounded-[1.35rem] rounded-tr-md bg-gradient-to-br from-[#1a73e8] via-[#5f7cf7] to-[#a142f4] text-white shadow-[0_12px_32px_rgba(66,133,244,0.24)] [overflow-wrap:anywhere]"
              : "rounded-[1.35rem] rounded-tl-md border border-white/80 bg-white/85 text-slate-800 shadow-[0_14px_45px_rgba(60,64,67,0.10)] backdrop-blur-xl"
          }`}
        >
          {isUser ? (
            <>
              {message.content}
              {streaming ? (
                <span className="ml-1 animate-pulse">...</span>
              ) : null}
            </>
          ) : (
            <div className="min-w-0 max-w-full">
              <MarkdownMessage
                content={message.content || (streaming ? "Thinking..." : "")}
              />
              {streaming ? (
                <span className="ml-1 animate-pulse">...</span>
              ) : null}
            </div>
          )}
          {message.citations && message.citations.length > 0 ? (
            <CitationList citations={message.citations} />
          ) : null}
        </div>
        <div className="flex items-center gap-2 px-1 text-xs text-slate-500">
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
    <div className="mt-4 border-t border-slate-200/80 pt-3 text-sm text-slate-500">
      <span>Sources:</span>
      <div className="mt-2 flex flex-wrap gap-2">
        {citations.map((citation, index) => (
          <span
            key={`${citation.file_id}:${index}`}
            className="inline-flex items-center gap-1 rounded-full border border-[#d2e3fc] bg-[#f8fbff] px-3 py-1 text-[#1a73e8]"
          >
            <span>{citation.filename}</span>
            <button
              type="button"
              onClick={() => void handleDownload(citation)}
              aria-label={`Download ${citation.filename}`}
              title={`Download ${citation.filename}`}
              className="rounded-full p-0.5 transition hover:bg-[#e8f0fe] hover:text-[#174ea6]"
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
        className={`inline-flex items-center rounded-full px-2 py-1 transition hover:bg-white/80 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 ${
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
        className={`inline-flex items-center rounded-full px-2 py-1 transition hover:bg-white/80 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 ${
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
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 transition hover:bg-white/80 hover:text-slate-900"
    >
      {children}
    </button>
  );
}

function Avatar({ isUser }: { isUser: boolean }) {
  return isUser ? (
    <div
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-slate-800 to-slate-950 text-white shadow-lg"
      aria-label="User"
    >
      <User className="h-5 w-5" />
    </div>
  ) : (
    <div
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#4285f4] via-[#34a853] to-[#fbbc04] p-[2px] text-[#1a73e8] shadow-lg"
      aria-label="Assistant"
    >
      <span className="flex h-full w-full items-center justify-center rounded-full bg-white/95">
        <Bot className="h-5 w-5" />
      </span>
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
