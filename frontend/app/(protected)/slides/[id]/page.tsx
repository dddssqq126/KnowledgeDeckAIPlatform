"use client";

import { isAxiosError } from "axios";
import {
  AlertCircle,
  Bot,
  Check,
  CheckCircle2,
  Copy,
  Download,
  Loader2,
  Pencil,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { ChatInput } from "../../../../components/ChatInput";
import { MarkdownWithCodeCopy } from "../../../../components/MarkdownWithCodeCopy";
import { useKbStore } from "../../../../lib/kb-store";
import { useLlmInfo } from "../../../../lib/llm-info";
import { useSlideStore } from "../../../../lib/slide-store";
import {
  type SlideMessage,
  type SlideMessageCitation,
  downloadSlideSession,
  getSlideSession,
  parseRenderMarker,
  renderSlideSession,
  streamSlideSession,
  stripOutlineReady,
} from "../../../../lib/slides";

function detailMessage(err: unknown): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return err instanceof Error ? err.message : "Failed";
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

export default function SlideSessionPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const sessionId = Number(params.id);

  const sessions = useSlideStore((s) => s.sessions);
  const slidesLoaded = useSlideStore((s) => s.loaded);
  const refreshSlides = useSlideStore((s) => s.refresh);
  const removeSession = useSlideStore((s) => s.remove);
  const renameSession = useSlideStore((s) => s.rename);
  const patchSession = useSlideStore((s) => s.patch);
  const bumpUpdatedAt = useSlideStore((s) => s.bumpUpdatedAt);

  const knowledgeBases = useKbStore((s) => s.kbs);
  const kbsLoaded = useKbStore((s) => s.loaded);
  const refreshKbs = useKbStore((s) => s.refresh);
  const llmInfo = useLlmInfo();

  const session = sessions.find((s) => s.id === sessionId);

  const [messages, setMessages] = useState<SlideMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [streamingCitations, setStreamingCitations] = useState<
    SlideMessageCitation[] | null
  >(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  // Render progress lives in the chat as a transient bubble that appears
  // while the API call is in flight. Once the backend returns, the
  // persisted [RENDERED:N]/[RENDER_FAILED:N] message takes its place in
  // the regular message list — so this state is *only* "rendering or null".
  type RenderState =
    | null
    | { startedAt: number; elapsedSec: number };
  const [renderState, setRenderState] = useState<RenderState>(null);

  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [savingTitle, setSavingTitle] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Hydrate ambient state.
  useEffect(() => {
    if (!slidesLoaded) refreshSlides();
  }, [slidesLoaded, refreshSlides]);
  useEffect(() => {
    if (!kbsLoaded) refreshKbs();
  }, [kbsLoaded, refreshKbs]);

  // Load this session's messages whenever the route id changes. Past
  // render results are persisted as [RENDERED:N] assistant messages, so
  // they reappear naturally in the history — no special seeding here.
  useEffect(() => {
    if (!Number.isFinite(sessionId)) return;
    let cancelled = false;
    setRenderState(null);
    (async () => {
      try {
        const detail = await getSlideSession(sessionId);
        if (cancelled) return;
        setMessages(detail.messages);
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Tick the elapsed counter while a render is in flight so the user sees
  // visible progress instead of a static spinner.
  useEffect(() => {
    if (!renderState) return;
    const startedAt = renderState.startedAt;
    const id = window.setInterval(() => {
      setRenderState((cur) =>
        cur ? { ...cur, elapsedSec: Math.round((Date.now() - startedAt) / 1000) } : cur,
      );
    }, 1000);
    return () => window.clearInterval(id);
  }, [renderState?.startedAt]);

  // Auto-scroll on new content.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, isStreaming]);

  // Triggered when the assistant emits [OUTLINE_READY]. Calls Presenton,
  // appends the persisted result message into the chat, and clears the
  // transient progress bubble. Network/HTTP errors show as a stream error
  // banner since they bypass the persisted message path.
  const triggerRender = useCallback(async () => {
    const startedAt = Date.now();
    setRenderState({ startedAt, elapsedSec: 0 });
    try {
      const result = await renderSlideSession(sessionId);
      patchSession(sessionId, {
        status: result.session.status,
        has_pptx: result.session.has_pptx,
      });
      setMessages((cur) => [...cur, result.message]);
    } catch (err) {
      setStreamError(detailMessage(err));
    } finally {
      setRenderState(null);
    }
  }, [sessionId, patchSession]);

  const handleSend = useCallback(
    async (text: string, useRag: boolean, kbIds: number[] | null) => {
      const optimistic: SlideMessage = {
        id: -Date.now(),
        role: "user",
        content: text,
        citations: null,
        created_at: new Date().toISOString(),
      };
      setMessages((cur) => [...cur, optimistic]);
      setStreamingText("");
      setStreamingCitations(null);
      setStreamError(null);
      setIsStreaming(true);

      let collected = "";
      let collectedCitations: SlideMessageCitation[] = [];

      await streamSlideSession(
        sessionId,
        { message: text, use_rag: useRag, kb_ids: kbIds },
        {
          onToken: (t) => {
            collected += t;
            setStreamingText(collected);
          },
          onCitations: (items) => {
            collectedCitations = items;
            setStreamingCitations(items);
          },
          onDone: (ready) => {
            const finalAssistant: SlideMessage = {
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
            bumpUpdatedAt(sessionId);
            refreshSlides();
            // [OUTLINE_READY] in the assistant message → automatically start
            // rendering. The user does not press a button.
            if (ready) {
              void triggerRender();
            }
          },
          onError: (msg) => {
            setStreamError(msg);
            setIsStreaming(false);
          },
        },
      );
    },
    [sessionId, bumpUpdatedAt, refreshSlides, triggerRender],
  );

  async function handleDownload() {
    if (!session) return;
    try {
      await downloadSlideSession(sessionId, session.title);
    } catch (err) {
      // Network or auth failure on the download. Surface inline with the
      // existing stream-error banner; the persisted [RENDERED] message
      // stays in place so the user can retry.
      setStreamError(detailMessage(err));
    }
  }

  async function handleDelete() {
    if (!session) return;
    if (!window.confirm(`Delete "${session.title}"?`)) return;
    await removeSession(sessionId);
    router.push("/slides");
  }

  async function handleRename(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!session) return;
    const trimmed = draftTitle.trim();
    if (!trimmed) return;
    setSavingTitle(true);
    setRenameError(null);
    try {
      await renameSession(sessionId, trimmed);
      setEditing(false);
    } catch (err) {
      setRenameError(detailMessage(err));
    } finally {
      setSavingTitle(false);
    }
  }

  if (slidesLoaded && !session) {
    return (
      <section className="h-full overflow-auto px-6 py-6">
        <div className="mx-auto max-w-3xl">
          <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-sm text-muted-foreground">
            Slide deck not found.
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex h-14 items-center justify-between border-b border-border bg-white/80 px-4">
        <div className="min-w-0 flex-1">
          {editing ? (
            <form onSubmit={handleRename} className="flex items-center gap-2">
              <input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                maxLength={200}
                autoFocus
                className="flex-1 rounded-md border border-border bg-white px-2 py-1 text-sm"
              />
              <button
                type="submit"
                disabled={savingTitle || !draftTitle.trim()}
                className="rounded-md bg-foreground px-2 py-1 text-xs text-white disabled:opacity-50"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
              >
                Cancel
              </button>
            </form>
          ) : (
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">
                {session?.title ?? "Loading…"}
              </span>
              <StatusBadge
                status={session?.status ?? "outlining"}
                hasPptx={session?.has_pptx ?? false}
              />
            </div>
          )}
          {renameError ? (
            <div className="mt-1 text-xs text-red-600">{renameError}</div>
          ) : null}
        </div>
        <div className="ml-3 mr-3 shrink-0 text-xs text-muted-foreground">
          Model: {llmInfo?.label ?? "…"}
        </div>
        {session && !editing ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setDraftTitle(session.title);
                setRenameError(null);
                setEditing(true);
              }}
              aria-label="Rename"
              className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={handleDelete}
              aria-label="Delete"
              className="rounded-md border border-border px-2 py-1 text-xs text-red-600 hover:bg-red-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}
      </header>

      <div className="flex-1 overflow-auto px-4 py-6">
        <div className="mx-auto max-w-5xl space-y-4">
          {messages.length === 0 && !isStreaming ? (
            <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-sm text-muted-foreground">
              Tell the planner what you want to make. It will ask follow-ups
              and propose an outline. When you confirm, render the PPTX.
            </div>
          ) : null}
          {messages.map((m) => (
            <SlideBubble
              key={m.id}
              message={m}
              onDownload={handleDownload}
            />
          ))}
          {isStreaming ? (
            <SlideBubble
              message={{
                id: -1,
                role: "assistant",
                content: streamingText || "…",
                citations: streamingCitations,
                created_at: new Date().toISOString(),
              }}
              streaming
              onDownload={handleDownload}
            />
          ) : null}
          {/* Transient bubble — only present while a render is in flight.
              Once the API returns, the persisted [RENDERED:N] message in
              `messages` takes its place. */}
          {renderState ? <RenderingBubble elapsedSec={renderState.elapsedSec} /> : null}
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
        disabled={isStreaming || renderState !== null}
        onSend={handleSend}
      />
    </section>
  );
}

function formatElapsed(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}:${String(sec).padStart(2, "0")}` : `${sec}s`;
}

/** Transient bubble shown only while a render is in flight. Disappears
 * the instant the persisted [RENDERED:N] message arrives in `messages`. */
function RenderingBubble({ elapsedSec }: { elapsedSec: number }) {
  return (
    <div className="flex items-start gap-2">
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-white text-foreground"
        aria-label="Slide Maker"
      >
        <Sparkles className="h-4 w-4" />
      </div>
      <div className="rounded-lg border border-border bg-white px-3 py-2 text-sm">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>
            Rendering presentation via Presenton…{" "}
            <span className="text-muted-foreground">
              ({formatElapsed(elapsedSec)})
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  hasPptx,
}: {
  status: string;
  hasPptx: boolean;
}) {
  const { label, tone } = (() => {
    if (status === "rendered" && hasPptx)
      return { label: "Rendered", tone: "bg-emerald-100 text-emerald-700" };
    if (status === "rendering")
      return { label: "Rendering…", tone: "bg-amber-100 text-amber-800" };
    if (status === "failed")
      return { label: "Failed", tone: "bg-red-100 text-red-700" };
    return { label: "Outlining", tone: "bg-muted text-muted-foreground" };
  })();
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${tone}`}>{label}</span>
  );
}

function SlideBubble({
  message,
  streaming = false,
  onDownload,
}: {
  message: SlideMessage;
  streaming?: boolean;
  onDownload: () => void;
}) {
  const isUser = message.role === "user";
  const ts = formatTimestamp(message.created_at);

  // Detect [RENDERED:N] / [RENDER_FAILED:N] markers on assistant turns and
  // render the special UI inline. Chat turns fall through to the regular
  // markdown body renderer below.
  const marker = !isUser ? parseRenderMarker(message.content) : { kind: "chat" as const, body: message.content };

  if (marker.kind === "rendered") {
    return (
      <div className="flex items-start gap-2">
        <Avatar isUser={false} />
        <div className="flex flex-col gap-1">
          <div className="rounded-lg border border-border bg-white px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-3">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
              <span>
                {marker.body || "Your presentation is ready."}{" "}
                <span className="text-muted-foreground">
                  (rendered in {formatElapsed(marker.elapsedSec)})
                </span>
              </span>
              <button
                type="button"
                onClick={onDownload}
                className="inline-flex items-center gap-1 rounded-md bg-foreground px-2 py-1 text-xs text-white hover:bg-foreground/90"
              >
                <Download className="h-3.5 w-3.5" /> Download .pptx
              </button>
            </div>
          </div>
          <div className="px-1 text-[10px] text-muted-foreground">{ts}</div>
        </div>
      </div>
    );
  }

  if (marker.kind === "render_failed") {
    return (
      <div className="flex items-start gap-2">
        <Avatar isUser={false} />
        <div className="flex flex-col gap-1">
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <div className="flex items-start gap-2">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div>Render failed after {formatElapsed(marker.elapsedSec)}.</div>
                {marker.body ? (
                  <div className="mt-1 text-xs">{marker.body}</div>
                ) : null}
              </div>
            </div>
          </div>
          <div className="px-1 text-[10px] text-muted-foreground">{ts}</div>
        </div>
      </div>
    );
  }

  const display = isUser ? message.content : stripOutlineReady(marker.body);
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
              ? "whitespace-pre-wrap bg-foreground text-white"
              : "border border-border bg-white text-foreground"
          }`}
        >
          {isUser ? (
            <>
              {display}
              {streaming ? <span className="ml-1 animate-pulse">▍</span> : null}
            </>
          ) : (
            <div className="markdown-body">
              <MarkdownWithCodeCopy content={display || (streaming ? "…" : "")} />
              {streaming ? <span className="ml-1 animate-pulse">▍</span> : null}
            </div>
          )}
          {message.citations && message.citations.length > 0 ? (
            <div className="mt-2 border-t border-border/40 pt-2 text-xs text-muted-foreground">
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
        <div className="flex items-center gap-2 px-1 text-[10px] text-muted-foreground">
          <span>{ts}</span>
          {!isUser && !streaming && message.content ? (
            <CopyButton text={display} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Avatar({ isUser }: { isUser: boolean }) {
  return isUser ? (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-white"
      aria-label="User"
    >
      <User className="h-4 w-4" />
    </div>
  ) : (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-white text-foreground"
      aria-label="Assistant"
    >
      <Bot className="h-4 w-4" />
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
      className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-muted hover:text-foreground"
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
