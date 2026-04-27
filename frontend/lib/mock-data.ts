"use client";

import type { ChatMessage, ChatSession, Citation, SessionDetail } from "./chat";
import type {
  KnowledgeBase,
  KnowledgeBaseCreated,
  KnowledgeFile,
} from "./knowledge-bases";
import type { LlmInfo } from "./llm-info";
import type {
  RenderResponse,
  SlideMessage,
  SlideMessageCitation,
  SlideSession,
  SlideSessionDetail,
  SlideStreamRequest,
} from "./slides";

let nextChatId = 3;
let nextMessageId = 100;
let nextKbId = 3;
let nextFileId = 20;
let nextSlideId = 3;
let nextSlideMessageId = 200;

const now = () => new Date().toISOString();
const shortWait = (ms = 30) => new Promise((r) => window.setTimeout(r, ms));

const llmInfo: LlmInfo = { label: "Mock GPT-4.1", model_id: "mock-gpt-4.1" };

let chatSessions: ChatSession[] = [
  { id: 1, title: "產品需求討論", created_at: now(), updated_at: now() },
  { id: 2, title: "Demo Chat", created_at: now(), updated_at: now() },
];

const chatMessages = new Map<number, ChatMessage[]>([
  [
    1,
    [
      { id: 1, role: "user", content: "這個專案要做什麼？", citations: null, created_at: now() },
      {
        id: 2,
        role: "assistant",
        content: "這是 mock data 範例，讓你不用後端也能看完整前端流程。",
        citations: [{ file_id: 11, filename: "product-brief.txt" }],
        created_at: now(),
      },
    ],
  ],
]);

let knowledgeBases: KnowledgeBase[] = [
  { id: 1, name: "產品文件", description: "Mock KB", file_count: 2, created_at: now() },
  { id: 2, name: "技術規格", description: "Mock KB", file_count: 1, created_at: now() },
];

const kbFiles = new Map<number, KnowledgeFile[]>([
  [
    1,
    [
      {
        id: 11,
        knowledge_base_id: 1,
        filename: "product-brief.txt",
        extension: "txt",
        size_bytes: 10240,
        status: "indexed",
        status_error: null,
        created_at: now(),
      },
      {
        id: 12,
        knowledge_base_id: 1,
        filename: "roadmap.md",
        extension: "md",
        size_bytes: 3000,
        status: "indexed",
        status_error: null,
        created_at: now(),
      },
    ],
  ],
  [
    2,
    [
      {
        id: 13,
        knowledge_base_id: 2,
        filename: "system-design.pdf",
        extension: "pdf",
        size_bytes: 443322,
        status: "indexed",
        status_error: null,
        created_at: now(),
      },
    ],
  ],
]);

let slideSessions: SlideSession[] = [
  { id: 1, title: "Sales Pitch", status: "rendered", has_pptx: true, created_at: now(), updated_at: now() },
  { id: 2, title: "Tech Overview", status: "outlining", has_pptx: false, created_at: now(), updated_at: now() },
];

const slideMessages = new Map<number, SlideMessage[]>([
  [
    1,
    [
      { id: 30, role: "user", content: "幫我做 5 頁業務簡報", citations: null, created_at: now() },
      { id: 31, role: "assistant", content: "這是簡報大綱... [OUTLINE_READY]", citations: null, created_at: now() },
      { id: 32, role: "assistant", content: "[RENDERED:4]已完成 mock 簡報", citations: null, created_at: now() },
    ],
  ],
]);

export const mockApi = {
  getLlmInfo: async (): Promise<LlmInfo> => {
    await shortWait();
    return llmInfo;
  },

  listChatSessions: async (): Promise<ChatSession[]> => {
    await shortWait();
    return [...chatSessions].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  },
  createChatSession: async (title?: string): Promise<ChatSession> => {
    const row: ChatSession = {
      id: nextChatId++,
      title: title?.trim() || `New Chat ${nextChatId - 1}`,
      created_at: now(),
      updated_at: now(),
    };
    chatSessions = [row, ...chatSessions];
    chatMessages.set(row.id, []);
    return row;
  },
  getChatSession: async (id: number): Promise<SessionDetail> => {
    await shortWait();
    const session = chatSessions.find((s) => s.id === id);
    if (!session) throw new Error("session_not_found");
    return { ...session, messages: chatMessages.get(id) ?? [] };
  },
  updateChatSession: async (id: number, title: string): Promise<ChatSession> => {
    const idx = chatSessions.findIndex((s) => s.id === id);
    if (idx < 0) throw new Error("session_not_found");
    chatSessions[idx] = { ...chatSessions[idx], title, updated_at: now() };
    return chatSessions[idx];
  },
  deleteChatSession: async (id: number): Promise<void> => {
    chatSessions = chatSessions.filter((s) => s.id !== id);
    chatMessages.delete(id);
  },
  streamChat: async (
    req: { session_id: number; message: string; kb_ids: number[] | null },
    handlers: {
      onToken: (text: string) => void;
      onCitations: (items: Citation[]) => void;
      onDone: () => void;
      onError: (message: string) => void;
    },
  ) => {
    try {
      const answer = `Mock 回覆：你問的是「${req.message}」。這裡是前端假資料模式。`;
      const cites: Citation[] = req.kb_ids?.length
        ? [{ file_id: 11, filename: "product-brief.txt" }]
        : [];
      const msgs = chatMessages.get(req.session_id) ?? [];
      msgs.push({ id: nextMessageId++, role: "user", content: req.message, citations: null, created_at: now() });
      if (cites.length) handlers.onCitations(cites);
      for (const token of answer.split(" ")) {
        handlers.onToken(`${token} `);
        await shortWait(20);
      }
      msgs.push({ id: nextMessageId++, role: "assistant", content: answer, citations: cites.length ? cites : null, created_at: now() });
      chatMessages.set(req.session_id, msgs);
      chatSessions = chatSessions.map((s) => (s.id === req.session_id ? { ...s, updated_at: now() } : s));
      handlers.onDone();
    } catch (e) {
      handlers.onError(e instanceof Error ? e.message : "mock_stream_error");
    }
  },

  listKnowledgeBases: async (): Promise<KnowledgeBase[]> => {
    await shortWait();
    return [...knowledgeBases];
  },
  createKnowledgeBase: async (input: { name: string; description?: string | null }): Promise<KnowledgeBaseCreated> => {
    const row: KnowledgeBase = {
      id: nextKbId++,
      name: input.name,
      description: input.description ?? null,
      file_count: 0,
      created_at: now(),
    };
    knowledgeBases = [row, ...knowledgeBases];
    kbFiles.set(row.id, []);
    return { id: row.id, name: row.name, description: row.description, created_at: row.created_at };
  },
  updateKnowledgeBase: async (id: number, input: { name?: string; description?: string | null }): Promise<KnowledgeBaseCreated> => {
    const idx = knowledgeBases.findIndex((k) => k.id === id);
    if (idx < 0) throw new Error("kb_not_found");
    const current = knowledgeBases[idx];
    knowledgeBases[idx] = {
      ...current,
      name: input.name ?? current.name,
      description: input.description === undefined ? current.description : input.description,
    };
    const row = knowledgeBases[idx];
    return { id: row.id, name: row.name, description: row.description, created_at: row.created_at };
  },
  deleteKnowledgeBase: async (id: number): Promise<void> => {
    knowledgeBases = knowledgeBases.filter((k) => k.id !== id);
    kbFiles.delete(id);
  },
  listFiles: async (kbId: number): Promise<KnowledgeFile[]> => {
    await shortWait();
    return [...(kbFiles.get(kbId) ?? [])];
  },
  uploadFile: async (kbId: number, file: File, onProgress?: (percent: number) => void): Promise<KnowledgeFile> => {
    onProgress?.(30);
    await shortWait(60);
    onProgress?.(70);
    await shortWait(60);
    const extension = file.name.includes(".") ? file.name.split(".").pop()?.toLowerCase() ?? "txt" : "txt";
    const row: KnowledgeFile = {
      id: nextFileId++,
      knowledge_base_id: kbId,
      filename: file.name,
      extension,
      size_bytes: file.size,
      status: "indexed",
      status_error: null,
      created_at: now(),
    };
    kbFiles.set(kbId, [row, ...(kbFiles.get(kbId) ?? [])]);
    knowledgeBases = knowledgeBases.map((k) => (k.id === kbId ? { ...k, file_count: (kbFiles.get(kbId) ?? []).length } : k));
    onProgress?.(100);
    return row;
  },
  deleteFile: async (kbId: number, fileId: number): Promise<void> => {
    const rows = (kbFiles.get(kbId) ?? []).filter((f) => f.id !== fileId);
    kbFiles.set(kbId, rows);
    knowledgeBases = knowledgeBases.map((k) => (k.id === kbId ? { ...k, file_count: rows.length } : k));
  },

  listSlideSessions: async (): Promise<SlideSession[]> => {
    await shortWait();
    return [...slideSessions].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  },
  createSlideSession: async (title?: string): Promise<SlideSession> => {
    const row: SlideSession = {
      id: nextSlideId++,
      title: title?.trim() || `New Deck ${nextSlideId - 1}`,
      status: "outlining",
      has_pptx: false,
      created_at: now(),
      updated_at: now(),
    };
    slideSessions = [row, ...slideSessions];
    slideMessages.set(row.id, []);
    return row;
  },
  getSlideSession: async (id: number): Promise<SlideSessionDetail> => {
    const session = slideSessions.find((s) => s.id === id);
    if (!session) throw new Error("slide_not_found");
    return { ...session, messages: slideMessages.get(id) ?? [] };
  },
  updateSlideSession: async (id: number, title: string): Promise<SlideSession> => {
    const idx = slideSessions.findIndex((s) => s.id === id);
    if (idx < 0) throw new Error("slide_not_found");
    slideSessions[idx] = { ...slideSessions[idx], title, updated_at: now() };
    return slideSessions[idx];
  },
  deleteSlideSession: async (id: number): Promise<void> => {
    slideSessions = slideSessions.filter((s) => s.id !== id);
    slideMessages.delete(id);
  },
  streamSlideSession: async (
    sessionId: number,
    req: SlideStreamRequest,
    handlers: {
      onToken: (text: string) => void;
      onCitations: (items: SlideMessageCitation[]) => void;
      onDone: (outlineReady: boolean) => void;
      onError: (message: string) => void;
    },
  ) => {
    try {
      const body = `這是 mock 簡報大綱：\n1. 問題\n2. 解法\n3. 成效\n[OUTLINE_READY]`;
      const items: SlideMessageCitation[] = req.kb_ids?.length
        ? [{ file_id: 13, filename: "system-design.pdf" }]
        : [];
      const msgs = slideMessages.get(sessionId) ?? [];
      msgs.push({ id: nextSlideMessageId++, role: "user", content: req.message, citations: null, created_at: now() });
      if (items.length) handlers.onCitations(items);
      for (const token of body.split(" ")) {
        handlers.onToken(`${token} `);
        await shortWait(20);
      }
      msgs.push({ id: nextSlideMessageId++, role: "assistant", content: body, citations: items.length ? items : null, created_at: now() });
      slideMessages.set(sessionId, msgs);
      slideSessions = slideSessions.map((s) => (s.id === sessionId ? { ...s, updated_at: now(), status: "outlining" } : s));
      handlers.onDone(true);
    } catch (e) {
      handlers.onError(e instanceof Error ? e.message : "mock_slide_stream_error");
    }
  },
  renderSlideSession: async (sessionId: number): Promise<RenderResponse> => {
    await shortWait(300);
    slideSessions = slideSessions.map((s) =>
      s.id === sessionId ? { ...s, status: "rendered", has_pptx: true, updated_at: now() } : s,
    );
    const session = slideSessions.find((s) => s.id === sessionId)!;
    const message: SlideMessage = {
      id: nextSlideMessageId++,
      role: "assistant",
      content: "[RENDERED:3]Mock render 完成，可下載檔案。",
      citations: null,
      created_at: now(),
    };
    slideMessages.set(sessionId, [...(slideMessages.get(sessionId) ?? []), message]);
    return { session, message };
  },
  downloadSlideSession: async (sessionId: number, fallbackTitle: string): Promise<void> => {
    const content = `Mock PPTX content for session ${sessionId}`;
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fallbackTitle}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
