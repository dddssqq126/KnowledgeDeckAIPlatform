"use client";

import { api } from "./api";
import { useAuthStore } from "./auth-store";
import { mockApi } from "./mock-data";
import { USE_MOCK_DATA } from "./mock-mode";

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

export async function createSession(title?: string): Promise<ChatSession> {
  if (USE_MOCK_DATA) return mockApi.createChatSession(title);
  const res = await api.post<ChatSession>("/chat/sessions", { title: title ?? null });
  return res.data;
}

export async function listSessions(): Promise<ChatSession[]> {
  if (USE_MOCK_DATA) return mockApi.listChatSessions();
  const res = await api.get<ChatSession[]>("/chat/sessions");
  return res.data;
}

export async function getSession(id: number): Promise<SessionDetail> {
  if (USE_MOCK_DATA) return mockApi.getChatSession(id);
  const res = await api.get<SessionDetail>(`/chat/sessions/${id}`);
  return res.data;
}

export async function updateSession(id: number, title: string): Promise<ChatSession> {
  if (USE_MOCK_DATA) return mockApi.updateChatSession(id, title);
  const res = await api.patch<ChatSession>(`/chat/sessions/${id}`, { title });
  return res.data;
}

export async function deleteSession(id: number): Promise<void> {
  if (USE_MOCK_DATA) return mockApi.deleteChatSession(id);
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

/**
 * Streams a chat reply via SSE using fetch + ReadableStream so we can attach
 * the Bearer token (EventSource cannot set headers).
 */
export async function streamChat(
  req: StreamRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (USE_MOCK_DATA) {
    await mockApi.streamChat(req, handlers);
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

export type AskOnceInput = {
  message: string;
  useRag: boolean;
  kbIds: number[] | null;
  onToken?: (text: string) => void;
};

export type AskOnceResult = {
  answer: string;
  citations: Citation[];
};

/**
 * One-shot Q&A for summary style usage: creates a temporary chat session,
 * streams exactly one answer, then deletes the temporary session.
 */
export async function askOnce(input: AskOnceInput): Promise<AskOnceResult> {
  const session = await createSession("One-shot Summary");
  let answer = "";
  let citations: Citation[] = [];
  try {
    await new Promise<void>((resolve, reject) => {
      void streamChat(
        {
          session_id: session.id,
          message: input.message,
          use_rag: input.useRag,
          kb_ids: input.kbIds,
        },
        {
          onToken: (text) => {
            answer += text;
            input.onToken?.(text);
          },
          onCitations: (items) => {
            citations = items;
          },
          onDone: () => resolve(),
          onError: (msg) => reject(new Error(msg)),
        },
      );
    });
    return { answer, citations };
  } finally {
    try {
      await deleteSession(session.id);
    } catch {
      // Cleanup is best-effort for one-shot mode.
    }
  }
}
