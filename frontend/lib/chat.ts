"use client";

import { api } from "./api";
import { useAuthStore } from "./auth-store";
import { mockAppendChatTurn, mockGetSharedSession, mockShareSession } from "./mock-data";
import { isMockDataMode } from "./mock-mode";

export type Citation = {
  file_id: number;
  filename: string;
  doc_type?: string | null;
  tags_topic?: string[];
  vendor?: string;
  platform?: string;
  knowledge_type?: string;
};

export type ChatSession = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatFeedback = "like" | "dislike";

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
};

export type SessionDetail = ChatSession & { messages: ChatMessage[] };

export type ChatShare = {
  token: string;
  url_path: string;
};

export type ChatSearchResult = {
  session_id: number;
  session_title: string;
  matched_role: "user" | "assistant" | null;
  snippet: string;
  created_at: string;
};

export async function createSession(title?: string): Promise<ChatSession> {
  const res = await api.post<ChatSession>("/chat/sessions", { title: title ?? null });
  return res.data;
}

export async function listSessions(): Promise<ChatSession[]> {
  const res = await api.get<ChatSession[]>("/chat/sessions");
  return res.data;
}

export async function getSession(id: number): Promise<SessionDetail> {
  const res = await api.get<SessionDetail>(`/chat/sessions/${id}`);
  return res.data;
}

export async function shareChatSession(id: number): Promise<ChatShare> {
  if (isMockDataMode()) return mockShareSession(id);
  const res = await api.post<ChatShare>(`/chat/sessions/${id}/share`);
  return res.data;
}

export async function getSharedChat(token: string): Promise<SessionDetail> {
  if (isMockDataMode()) return mockGetSharedSession(token);
  const res = await api.get<SessionDetail>(`/chat/shares/${encodeURIComponent(token)}`);
  return res.data;
}

export async function updateSession(id: number, title: string): Promise<ChatSession> {
  const res = await api.patch<ChatSession>(`/chat/sessions/${id}`, { title });
  return res.data;
}

export async function deleteSession(id: number): Promise<void> {
  await api.delete(`/chat/sessions/${id}`);
}

export async function searchChatSessions(q: string): Promise<ChatSearchResult[]> {
  const res = await api.get<ChatSearchResult[]>("/chat/search", { params: { q } });
  return res.data;
}



export async function sendMessageFeedback(
  messageId: number,
  feedback: ChatFeedback,
): Promise<void> {
  await api.post(`/chat/messages/${messageId}/feedback`, { feedback });
}

export type StreamRequest = {
  session_id: number;
  message: string;
  use_rag: boolean;
  kb_ids: number[] | null;
};

export type StreamHandlers = {
  onToken: (text: string) => void;
  onCitations: (items: Citation[]) => void;
  onDone: () => void;
  onError: (message: string) => void;
};

/**
 * Streams a chat reply via SSE using fetch + ReadableStream so we can attach
 * the Bearer token (EventSource cannot set headers).
 */
export async function streamChat(
  req: StreamRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (isMockDataMode()) {
    await mockStreamChat(req, handlers, signal);
    return;
  }

  const token = useAuthStore.getState().token;
  const baseURL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
  let res: Response;
  try {
    res = await fetch(`${baseURL}/chat/stream`, {
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
    // SSE frames are separated by a blank line ("\n\n"). Process complete
    // frames; keep the trailing partial frame in the buffer.
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
      else if (event === "done") handlers.onDone();
      else if (event === "error") handlers.onError(parsed.message ?? "stream error");
    }
  }
}

async function mockStreamChat(
  req: StreamRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const { answer, citations } = mockAppendChatTurn(
    req.session_id,
    req.message,
    req.use_rag,
    req.kb_ids,
  );
  handlers.onCitations(citations);
  for (const token of chunkText(answer)) {
    if (signal?.aborted) {
      handlers.onError("cancelled");
      return;
    }
    handlers.onToken(token);
    await wait(22);
  }
  handlers.onDone();
}

function chunkText(text: string): string[] {
  return text.match(/.{1,18}(\s|$)/g) ?? [text];
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
