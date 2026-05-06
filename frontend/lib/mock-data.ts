"use client";

import type { Citation, ChatMessage, ChatSession, SessionDetail } from "./chat";
import type {
  KnowledgeBase,
  KnowledgeBaseCreated,
  KnowledgeFile,
} from "./knowledge-bases";
import type {
  RenderResponse,
  SlideMessage,
  SlideMessageCitation,
  SlideSession,
  SlideSessionDetail,
} from "./slides";

const now = new Date("2026-05-03T08:30:00.000Z");

function iso(minutesAgo: number): string {
  return new Date(now.getTime() - minutesAgo * 60_000).toISOString();
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

let nextKbId = 4;
let nextFileId = 20;
let nextChatId = 4;
let nextChatMessageId = 30;
let nextSlideId = 4;
let nextSlideMessageId = 40;

let knowledgeBases: KnowledgeBase[] = [
  {
    id: 1,
    name: "Engineering Handbook",
    description: "Architecture notes, service contracts, and coding examples.",
    file_count: 4,
    created_at: iso(5200),
  },
  {
    id: 2,
    name: "Product Research",
    description: "User interviews and market synthesis for deck generation.",
    file_count: 3,
    created_at: iso(4100),
  },
  {
    id: 3,
    name: "Launch Enablement",
    description: "Sales narrative, FAQ, and rollout plan.",
    file_count: 2,
    created_at: iso(1800),
  },
];

let filesByKb: Record<number, KnowledgeFile[]> = {
  1: [
    file(11, 1, "react_hooks.txt", "txt", 18_240, iso(4800)),
    file(12, 1, "python_asyncio.txt", "txt", 22_110, iso(4620)),
    file(13, 1, "postgres_indexing.txt", "txt", 16_880, iso(4500)),
    file(14, 1, "OrderService.cs", "cs", 9_420, iso(4300)),
  ],
  2: [
    file(15, 2, "interview_summary.md", "md", 31_260, iso(2900)),
    file(16, 2, "market_map.pdf", "pdf", 1_830_400, iso(2650)),
    file(17, 2, "competitor_notes.txt", "txt", 14_220, iso(2400)),
  ],
  3: [
    file(18, 3, "launch_faq.md", "md", 12_800, iso(900)),
    file(19, 3, "sales_pitch.pptx", "pptx", 2_480_000, iso(760)),
  ],
};

let chatSessions: ChatSession[] = [
  chatSession(1, "RAG onboarding checklist", iso(160), iso(45)),
  chatSession(2, "Postgres indexing explanation", iso(980), iso(920)),
  chatSession(3, "Launch FAQ assistant", iso(1450), iso(1300)),
];

let chatMessages: Record<number, ChatMessage[]> = {
  1: [
    chatMessage(21, "user", "Summarize what is inside my RAG databases.", null, iso(55)),
    chatMessage(
      22,
      "assistant",
      "You currently have three mock RAG databases: Engineering Handbook, Product Research, and Launch Enablement. They cover implementation notes, research material, and go-to-market assets.",
      citationsFor([11, 15, 18]),
      iso(54),
    ),
  ],
  2: [
    chatMessage(23, "user", "When should we add a Postgres index?", null, iso(925)),
    chatMessage(
      24,
      "assistant",
      "Add an index when a query repeatedly filters, joins, or sorts over a column with enough selectivity to beat a sequential scan. Validate with `EXPLAIN ANALYZE` before and after.",
      citationsFor([13]),
      iso(924),
    ),
  ],
  3: [],
};

let slideSessions: SlideSession[] = [
  slideSession(1, "KnowledgeDeck investor walkthrough", "rendered", true, iso(1200), iso(65)),
  slideSession(2, "RAG quality review", "outlining", false, iso(680), iso(500)),
  slideSession(3, "Launch enablement deck", "rendered", true, iso(140), iso(80)),
];

let slideMessages: Record<number, SlideMessage[]> = {
  1: [
    slideMessage(31, "user", "Create a concise deck about KnowledgeDeck.", null, iso(80)),
    slideMessage(
      32,
      "assistant",
      "## Outline\n\n1. Product promise\n2. RAG workflow\n3. Slide generation\n4. Deployment model\n5. Roadmap\n\n[OUTLINE_READY]",
      citationsForSlides([11, 15]),
      iso(79),
    ),
    slideMessage(
      33,
      "assistant",
      "[RENDERED:8] Mock PPTX generated with the Presenton renderer path.",
      null,
      iso(78),
    ),
  ],
  2: [
    slideMessage(34, "user", "Plan a review deck for RAG retrieval quality.", null, iso(505)),
    slideMessage(
      35,
      "assistant",
      "We can frame it as: corpus coverage, retrieval scoring, reranking, answer quality, and next experiments. Ask me to render when the sections look right.",
      citationsForSlides([13, 16]),
      iso(504),
    ),
  ],
  3: [
    slideMessage(36, "assistant", "[RENDERED:6] Launch enablement deck is ready.", null, iso(80)),
  ],
};

export type RagDatabaseSummary = {
  id: number;
  name: string;
  description: string | null;
  file_count: number;
  vector_count: number;
  embedding_model: string;
  status: "ready" | "empty";
  files: KnowledgeFile[];
  created_at: string;
};

export type PresentonMockPresentation = {
  id: string;
  title: string;
  template: string;
  status: "draft" | "exported";
  updated_at: string;
  slides: number;
};

export const presentonMockPresentations: PresentonMockPresentation[] = [
  {
    id: "pr-101",
    title: "AI Knowledge Platform Overview",
    template: "Neo General",
    status: "exported",
    updated_at: iso(40),
    slides: 9,
  },
  {
    id: "pr-102",
    title: "Quarterly RAG Quality Report",
    template: "Report",
    status: "draft",
    updated_at: iso(260),
    slides: 12,
  },
  {
    id: "pr-103",
    title: "Developer Onboarding",
    template: "Code",
    status: "exported",
    updated_at: iso(1440),
    slides: 7,
  },
];

export const presentonMockTemplates = [
  { name: "Standard", category: "General", slides: 10, tone: "Clean business" },
  { name: "Modern", category: "Pitch", slides: 9, tone: "High contrast editorial" },
  { name: "Report", category: "Analytics", slides: 14, tone: "Data-heavy executive" },
  { name: "Education", category: "Learning", slides: 11, tone: "Structured teaching" },
  { name: "Code", category: "Technical", slides: 8, tone: "Developer documentation" },
  { name: "Product Overview", category: "Product", slides: 13, tone: "Launch narrative" },
];

export const presentonMockThemes = [
  { name: "Neo General", colors: ["#5146E5", "#111827", "#F8FAFC"] },
  { name: "Swift", colors: ["#EA580C", "#0F172A", "#FFF7ED"] },
  { name: "Education", colors: ["#047857", "#1F2937", "#ECFDF5"] },
  { name: "Report", colors: ["#2563EB", "#334155", "#EFF6FF"] },
];

function file(
  id: number,
  kbId: number,
  filename: string,
  extension: string,
  size: number,
  createdAt: string,
): KnowledgeFile {
  return {
    id,
    knowledge_base_id: kbId,
    filename,
    extension,
    size_bytes: size,
    status: "indexed",
    status_error: null,
    created_at: createdAt,
  };
}

function chatSession(id: number, title: string, createdAt: string, updatedAt: string): ChatSession {
  return { id, title, created_at: createdAt, updated_at: updatedAt };
}

function chatMessage(
  id: number,
  role: ChatMessage["role"],
  content: string,
  citations: Citation[] | null,
  createdAt: string,
): ChatMessage {
  return { id, role, content, citations, created_at: createdAt };
}

function slideSession(
  id: number,
  title: string,
  status: SlideSession["status"],
  hasPptx: boolean,
  createdAt: string,
  updatedAt: string,
): SlideSession {
  return { id, title, status, has_pptx: hasPptx, created_at: createdAt, updated_at: updatedAt };
}

function slideMessage(
  id: number,
  role: SlideMessage["role"],
  content: string,
  citations: SlideMessageCitation[] | null,
  createdAt: string,
): SlideMessage {
  return { id, role, content, citations, created_at: createdAt };
}

function allFiles(): KnowledgeFile[] {
  return Object.values(filesByKb).flat();
}

function citationsFor(ids: number[]): Citation[] {
  return allFiles()
    .filter((f) => ids.includes(f.id))
    .map((f) => ({ file_id: f.id, filename: f.filename }));
}

function citationsForSlides(ids: number[]): SlideMessageCitation[] {
  return citationsFor(ids);
}

function syncFileCount(kbId: number): void {
  const count = filesByKb[kbId]?.length ?? 0;
  knowledgeBases = knowledgeBases.map((kb) =>
    kb.id === kbId ? { ...kb, file_count: count } : kb,
  );
}

function sortByUpdated<T extends { updated_at?: string; created_at: string }>(items: T[]): T[] {
  return [...items].sort((a, b) =>
    (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at),
  );
}

export const mockUser = { id: 1, username: "mock-admin" };

export function mockLogin(username: string) {
  return {
    token: "mock-token",
    user: { ...mockUser, username: username.trim() || mockUser.username },
  };
}

export function mockListKnowledgeBases(): KnowledgeBase[] {
  return clone(knowledgeBases);
}

export function mockCreateKnowledgeBase(input: {
  name: string;
  description?: string | null;
}): KnowledgeBaseCreated {
  const created: KnowledgeBase = {
    id: nextKbId++,
    name: input.name,
    description: input.description ?? null,
    file_count: 0,
    created_at: new Date().toISOString(),
  };
  knowledgeBases = [created, ...knowledgeBases];
  filesByKb[created.id] = [];
  return clone(created);
}

export function mockUpdateKnowledgeBase(
  id: number,
  input: { name?: string; description?: string | null },
): KnowledgeBaseCreated {
  let updated: KnowledgeBase | null = null;
  knowledgeBases = knowledgeBases.map((kb) => {
    if (kb.id !== id) return kb;
    updated = {
      ...kb,
      name: input.name ?? kb.name,
      description: input.description === undefined ? kb.description : input.description,
    };
    return updated;
  });
  if (!updated) throw new Error("Knowledge base not found");
  return clone(updated);
}

export function mockDeleteKnowledgeBase(id: number): void {
  knowledgeBases = knowledgeBases.filter((kb) => kb.id !== id);
  delete filesByKb[id];
}

export function mockListFiles(kbId: number): KnowledgeFile[] {
  return clone(filesByKb[kbId] ?? []);
}

export function mockUploadFile(kbId: number, upload: File): KnowledgeFile {
  const extension = upload.name.includes(".")
    ? upload.name.split(".").pop()!.toLowerCase()
    : "txt";
  const row = file(
    nextFileId++,
    kbId,
    upload.name,
    extension,
    upload.size || 4096,
    new Date().toISOString(),
  );
  filesByKb[kbId] = [row, ...(filesByKb[kbId] ?? [])];
  syncFileCount(kbId);
  return clone(row);
}

export function mockDeleteFile(kbId: number, fileId: number): void {
  filesByKb[kbId] = (filesByKb[kbId] ?? []).filter((file) => file.id !== fileId);
  syncFileCount(kbId);
}

export function mockListSessions(): ChatSession[] {
  return clone(sortByUpdated(chatSessions));
}

export function mockCreateSession(title?: string): ChatSession {
  const created = chatSession(
    nextChatId++,
    title?.trim() || "New chat",
    new Date().toISOString(),
    new Date().toISOString(),
  );
  chatSessions = [created, ...chatSessions];
  chatMessages[created.id] = [];
  return clone(created);
}

export function mockGetSession(id: number): SessionDetail {
  const session = chatSessions.find((item) => item.id === id);
  if (!session) throw new Error("Chat session not found");
  return clone({ ...session, messages: chatMessages[id] ?? [] });
}

export function mockUpdateSession(id: number, title: string): ChatSession {
  let updated: ChatSession | null = null;
  chatSessions = chatSessions.map((session) => {
    if (session.id !== id) return session;
    updated = { ...session, title, updated_at: new Date().toISOString() };
    return updated;
  });
  if (!updated) throw new Error("Chat session not found");
  return clone(updated);
}

export function mockDeleteSession(id: number): void {
  chatSessions = chatSessions.filter((session) => session.id !== id);
  delete chatMessages[id];
}

export function mockAppendChatTurn(
  sessionId: number,
  text: string,
  useRag: boolean,
  kbIds: number[] | null,
): { answer: string; citations: Citation[] } {
  const selectedFiles = selectCitationFiles(kbIds);
  const citations = useRag ? selectedFiles.slice(0, 3).map((f) => ({ file_id: f.id, filename: f.filename })) : [];
  const answer = useRag
    ? `Mock LLM answer grounded in ${citations.length || "the selected"} RAG source(s).\n\nYou asked: "${text}"\n\nA practical next step is to compare the cited files, extract the shared decisions, and turn them into a short checklist.`
    : `Mock LLM answer without RAG.\n\nYou asked: "${text}"\n\nI can respond from general model context, but source citations are disabled for this turn.`;
  const createdAt = new Date().toISOString();
  chatMessages[sessionId] = [
    ...(chatMessages[sessionId] ?? []),
    chatMessage(nextChatMessageId++, "user", text, null, createdAt),
    chatMessage(nextChatMessageId++, "assistant", answer, citations.length ? citations : null, createdAt),
  ];
  touchChatSession(sessionId, text);
  return { answer, citations };
}

function touchChatSession(sessionId: number, firstMessageTitle?: string): void {
  chatSessions = chatSessions.map((session) => {
    if (session.id !== sessionId) return session;
    const hasGenericTitle = session.title === "New chat";
    return {
      ...session,
      title: hasGenericTitle && firstMessageTitle ? firstMessageTitle.slice(0, 44) : session.title,
      updated_at: new Date().toISOString(),
    };
  });
}

function selectCitationFiles(kbIds: number[] | null): KnowledgeFile[] {
  if (!kbIds || kbIds.length === 0) return allFiles();
  return kbIds.flatMap((id) => filesByKb[id] ?? []);
}

export function mockListSlideSessions(): SlideSession[] {
  return clone(sortByUpdated(slideSessions));
}

export function mockCreateSlideSession(title?: string): SlideSession {
  const created = slideSession(
    nextSlideId++,
    title?.trim() || "New slide deck",
    "outlining",
    false,
    new Date().toISOString(),
    new Date().toISOString(),
  );
  slideSessions = [created, ...slideSessions];
  slideMessages[created.id] = [];
  return clone(created);
}

export function mockGetSlideSession(id: number): SlideSessionDetail {
  const session = slideSessions.find((item) => item.id === id);
  if (!session) throw new Error("Slide session not found");
  return clone({ ...session, messages: slideMessages[id] ?? [] });
}

export function mockUpdateSlideSession(id: number, title: string): SlideSession {
  let updated: SlideSession | null = null;
  slideSessions = slideSessions.map((session) => {
    if (session.id !== id) return session;
    updated = { ...session, title, updated_at: new Date().toISOString() };
    return updated;
  });
  if (!updated) throw new Error("Slide session not found");
  return clone(updated);
}

export function mockDeleteSlideSession(id: number): void {
  slideSessions = slideSessions.filter((session) => session.id !== id);
  delete slideMessages[id];
}

export function mockAppendSlideTurn(
  sessionId: number,
  text: string,
  useRag: boolean,
  kbIds: number[] | null,
): { answer: string; citations: SlideMessageCitation[]; outlineReady: boolean } {
  const selectedFiles = selectCitationFiles(kbIds);
  const citations = useRag
    ? selectedFiles.slice(0, 3).map((f) => ({ file_id: f.id, filename: f.filename }))
    : [];
  const outlineReady = /render|generate|deck|ppt|slide/i.test(text);
  const answer = `## Mock Presenton outline\n\n1. Opening narrative\n2. Evidence from selected knowledge bases\n3. Visual storyline\n4. Risks and mitigations\n5. Recommended next steps\n\n${outlineReady ? "[OUTLINE_READY]" : "Tell me to render when this structure looks right."}`;
  const createdAt = new Date().toISOString();
  slideMessages[sessionId] = [
    ...(slideMessages[sessionId] ?? []),
    slideMessage(nextSlideMessageId++, "user", text, null, createdAt),
    slideMessage(nextSlideMessageId++, "assistant", answer, citations.length ? citations : null, createdAt),
  ];
  touchSlideSession(sessionId, text, { status: "outlining" });
  return { answer, citations, outlineReady };
}

export function mockRenderSlideSession(sessionId: number): RenderResponse {
  const session = touchSlideSession(sessionId, undefined, {
    status: "rendered",
    has_pptx: true,
  });
  const message = slideMessage(
    nextSlideMessageId++,
    "assistant",
    "[RENDERED:5] Mock PPTX generated. In backend mode this would call Presenton and return a real file.",
    null,
    new Date().toISOString(),
  );
  slideMessages[sessionId] = [...(slideMessages[sessionId] ?? []), message];
  return clone({ session, message });
}

function touchSlideSession(
  sessionId: number,
  firstMessageTitle?: string,
  patch?: Partial<SlideSession>,
): SlideSession {
  let updated: SlideSession | null = null;
  slideSessions = slideSessions.map((session) => {
    if (session.id !== sessionId) return session;
    const hasGenericTitle = session.title === "New slide deck";
    updated = {
      ...session,
      ...patch,
      title: hasGenericTitle && firstMessageTitle ? firstMessageTitle.slice(0, 52) : session.title,
      updated_at: new Date().toISOString(),
    };
    return updated;
  });
  if (!updated) throw new Error("Slide session not found");
  return updated;
}

export function mockListRagDatabases(): RagDatabaseSummary[] {
  return clone(
    knowledgeBases.map((kb) => {
      const files = filesByKb[kb.id] ?? [];
      return {
        ...kb,
        files,
        vector_count: files.reduce((sum, item) => sum + Math.max(8, Math.ceil(item.size_bytes / 900)), 0),
        embedding_model: "BAAI/bge-m3",
        status: files.length > 0 ? "ready" : "empty",
      };
    }),
  );
}

export function mockDownloadSlideBlob(title: string): Blob {
  const content = [
    "Mock PPTX placeholder",
    `Title: ${title}`,
    "Switch NEXT_PUBLIC_DATA_MODE=backend to download real Presenton output.",
  ].join("\n");
  return new Blob([content], {
    type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  });
}
