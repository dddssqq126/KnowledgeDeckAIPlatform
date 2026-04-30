"use client";

import { api } from "./api";
import { useAuthStore } from "./auth-store";
import { USE_MOCK_DATA } from "./runtime-config";

export type Citation = { file_id: number; filename: string };

export type ChatSession = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
};

export type SessionDetail = ChatSession & { messages: ChatMessage[] };

const mockSessions = new Map<number, SessionDetail>();
let mockNextSessionId = 1;
let mockNextMessageId = 1;

function nowIso() {
  return new Date().toISOString();
}

function ensureMockSeedSession() {
  if (!USE_MOCK_DATA) return;
  if (mockSessions.size > 0) return;
  const now = nowIso();
  const id = mockNextSessionId++;
  mockSessions.set(id, {
    id,
    title: "Mock RAG Chat",
    created_at: now,
    updated_at: now,
    messages: [
      {
        id: mockNextMessageId++,
        role: "assistant",
        content: "Mock mode is enabled. Ask me anything and I will answer with mock RAG data.",
        citations: [{ file_id: 1, filename: "mock-source.txt" }],
        created_at: now,
      },
    ],
  });
}

export async function createSession(title?: string): Promise<ChatSession> {
  if (USE_MOCK_DATA) {
    ensureMockSeedSession();
    const now = nowIso();
    const session: SessionDetail = {
      id: mockNextSessionId++,
      title: title?.trim() || "New Chat",
      created_at: now,
      updated_at: now,
      messages: [],
    };
    mockSessions.set(session.id, session);
    return session;
  }
  const res = await api.post<ChatSession>("/chat/sessions", { title: title ?? null });
  return res.data;
}

export async function listSessions(): Promise<ChatSession[]> {
  if (USE_MOCK_DATA) {
    ensureMockSeedSession();
    return Array.from(mockSessions.values()).map(({ messages, ...session }) => session);
  }
  const res = await api.get<ChatSession[]>("/chat/sessions");
  return res.data;
}

export async function getSession(id: number): Promise<SessionDetail> {
  if (USE_MOCK_DATA) {
    ensureMockSeedSession();
    const session = mockSessions.get(id);
    if (!session) throw new Error("Not found");
    return session;
  }
  const res = await api.get<SessionDetail>(`/chat/sessions/${id}`);
  return res.data;
}

export async function updateSession(id: number, title: string): Promise<ChatSession> {
  if (USE_MOCK_DATA) {
    ensureMockSeedSession();
    const session = mockSessions.get(id);
    if (!session) throw new Error("Not found");
    session.title = title;
    session.updated_at = nowIso();
    return { id: session.id, title: session.title, created_at: session.created_at, updated_at: session.updated_at };
  }
  const res = await api.patch<ChatSession>(`/chat/sessions/${id}`, { title });
  return res.data;
}

export async function deleteSession(id: number): Promise<void> {
  if (USE_MOCK_DATA) {
    ensureMockSeedSession();
    mockSessions.delete(id);
    return;
  }
  await api.delete(`/chat/sessions/${id}`);
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

export async function streamChat(
  req: StreamRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (USE_MOCK_DATA) {
    ensureMockSeedSession();
    const session = mockSessions.get(req.session_id);
    if (!session) {
      handlers.onError("Session not found");
      return;
    }
    const userMessage: ChatMessage = {
      id: mockNextMessageId++, role: "user", content: req.message, citations: null, created_at: nowIso(),
    };
    session.messages.push(userMessage);
    const reply = req.use_rag
      ? `Mock RAG answer: I found relevant context for "${req.message}".`
      : `Mock answer: ${req.message}`;
    handlers.onToken(reply);
    handlers.onCitations(req.use_rag ? [{ file_id: 1, filename: "mock-source.txt" }] : []);
    const assistantMessage: ChatMessage = {
      id: mockNextMessageId++, role: "assistant", content: reply,
      citations: req.use_rag ? [{ file_id: 1, filename: "mock-source.txt" }] : null,
      created_at: nowIso(),
    };
    session.messages.push(assistantMessage);
    session.updated_at = nowIso();
    handlers.onDone();
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
