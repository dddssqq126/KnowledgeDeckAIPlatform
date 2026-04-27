"use client";

import { api } from "./api";
import { useAuthStore } from "./auth-store";
import { mockApi } from "./mock-data";
import { USE_MOCK_DATA } from "./mock-mode";

export type SlideStatus = "outlining" | "rendering" | "rendered" | "failed";

export type SlideSession = {
  id: number;
  title: string;
  status: SlideStatus;
  has_pptx: boolean;
  created_at: string;
  updated_at: string;
};

export type SlideMessageCitation = { file_id: number; filename: string };

export type SlideMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: SlideMessageCitation[] | null;
  created_at: string;
};

export type SlideSessionDetail = SlideSession & {
  messages: SlideMessage[];
};

export const OUTLINE_READY_MARKER = "[OUTLINE_READY]";
// Matches the marker plus any optional `key=value` args inside the brackets,
// e.g. `[OUTLINE_READY]`, `[OUTLINE_READY template=modern]`,
// `[OUTLINE_READY template=professional language=Spanish]`.
const OUTLINE_READY_RE = /\[OUTLINE_READY(?:\s+[^\]]+)?\]/;

// --- Sessions CRUD ---

export async function createSlideSession(title?: string): Promise<SlideSession> {
  if (USE_MOCK_DATA) return mockApi.createSlideSession(title);
  const res = await api.post<SlideSession>("/slide-sessions", {
    title: title ?? null,
  });
  return res.data;
}

export async function listSlideSessions(): Promise<SlideSession[]> {
  if (USE_MOCK_DATA) return mockApi.listSlideSessions();
  const res = await api.get<SlideSession[]>("/slide-sessions");
  return res.data;
}

export async function getSlideSession(id: number): Promise<SlideSessionDetail> {
  if (USE_MOCK_DATA) return mockApi.getSlideSession(id);
  const res = await api.get<SlideSessionDetail>(`/slide-sessions/${id}`);
  return res.data;
}

export async function updateSlideSession(
  id: number,
  title: string,
): Promise<SlideSession> {
  if (USE_MOCK_DATA) return mockApi.updateSlideSession(id, title);
  const res = await api.patch<SlideSession>(`/slide-sessions/${id}`, { title });
  return res.data;
}

export async function deleteSlideSession(id: number): Promise<void> {
  if (USE_MOCK_DATA) return mockApi.deleteSlideSession(id);
  await api.delete(`/slide-sessions/${id}`);
}

// --- Streaming + Render + Download ---

export type SlideStreamRequest = {
  message: string;
  use_rag: boolean;
  kb_ids: number[] | null;
};

export type SlideStreamHandlers = {
  onToken: (text: string) => void;
  onCitations: (items: SlideMessageCitation[]) => void;
  /** outlineReady is true on the turn the assistant emitted [OUTLINE_READY]. */
  onDone: (outlineReady: boolean) => void;
  onError: (message: string) => void;
};

export async function streamSlideSession(
  sessionId: number,
  req: SlideStreamRequest,
  handlers: SlideStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (USE_MOCK_DATA) {
    await mockApi.streamSlideSession(sessionId, req, handlers);
    return;
  }
  const token = useAuthStore.getState().token;
  const baseURL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
  let res: Response;
  try {
    res = await fetch(`${baseURL}/slide-sessions/${sessionId}/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(req),
      signal,
    });
  } catch (e) {
    handlers.onError(e instanceof Error ? e.message : "network error");
    return;
  }
  if (!res.ok || !res.body) {
    handlers.onError(`HTTP ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      if (!event) continue;
      let parsed: any = {};
      if (data) {
        try {
          parsed = JSON.parse(data);
        } catch {
          parsed = { raw: data };
        }
      }
      if (event === "token") handlers.onToken(parsed.text ?? "");
      else if (event === "citations") handlers.onCitations(parsed.items ?? []);
      else if (event === "done") handlers.onDone(parsed.outline_ready === true);
      else if (event === "error") handlers.onError(parsed.message ?? "stream error");
    }
  }
}

export type RenderResponse = {
  session: SlideSession;
  message: SlideMessage;
};

export async function renderSlideSession(
  sessionId: number,
  opts?: { template?: string; language?: string },
): Promise<RenderResponse> {
  if (USE_MOCK_DATA) return mockApi.renderSlideSession(sessionId);
  const res = await api.post<RenderResponse>(
    `/slide-sessions/${sessionId}/render`,
    {
      template: opts?.template ?? "general",
      language: opts?.language ?? "English",
    },
  );
  return res.data;
}

/**
 * Persisted render-status messages carry one of these markers in their
 * content. Frontend strips the marker and renders a Download button (or
 * an error block) inline with the rest of the chat.
 */
const RENDERED_MARKER_RE = /^\[RENDERED:(\d+)\]\s*/;
const RENDER_FAILED_MARKER_RE = /^\[RENDER_FAILED:(\d+)\]\s*/;

export type RenderMarker =
  | { kind: "chat"; body: string }
  | { kind: "rendered"; elapsedSec: number; body: string }
  | { kind: "render_failed"; elapsedSec: number; body: string };

export function parseRenderMarker(content: string): RenderMarker {
  let m = RENDERED_MARKER_RE.exec(content);
  if (m) {
    return {
      kind: "rendered",
      elapsedSec: Number(m[1]),
      body: content.slice(m[0].length),
    };
  }
  m = RENDER_FAILED_MARKER_RE.exec(content);
  if (m) {
    return {
      kind: "render_failed",
      elapsedSec: Number(m[1]),
      body: content.slice(m[0].length),
    };
  }
  return { kind: "chat", body: content };
}

export async function downloadSlideSession(
  sessionId: number,
  fallbackTitle: string,
): Promise<void> {
  if (USE_MOCK_DATA) return mockApi.downloadSlideSession(sessionId, fallbackTitle);
  const token = useAuthStore.getState().token;
  const baseURL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
  const res = await fetch(`${baseURL}/slide-sessions/${sessionId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const disp = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disp);
  const filename = match?.[1] ?? `${fallbackTitle}.pptx`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Strips the OUTLINE_READY marker (with or without args) from a message
 * body for display. */
export function stripOutlineReady(content: string): string {
  return content.replace(OUTLINE_READY_RE, "").trimEnd();
}

/** True if the assistant message body contains the OUTLINE_READY marker
 * (with or without args). */
export function hasOutlineReady(content: string): boolean {
  return OUTLINE_READY_RE.test(content);
}
