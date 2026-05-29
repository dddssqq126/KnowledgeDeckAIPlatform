"use client";

import { LONG_RUNNING_REQUEST_TIMEOUT_MS, api } from "./api";
import { downloadBlob, safeFilename } from "./download";
import { isMockDataMode } from "./mock-mode";

export type FileStatus =
  | "uploaded"
  | "parsing"
  | "parsed"
  | "embedding"
  | "indexed"
  | "failed";

export type KnowledgeBase = {
  id: number;
  name: string;
  description: string | null;
  file_count: number;
  created_at: string;
};

export type KnowledgeBaseCreated = {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
};

export type KnowledgeFile = {
  id: number;
  knowledge_base_id: number;
  filename: string;
  extension: string;
  size_bytes: number;
  status: FileStatus;
  status_error: string | null;
  created_at: string;
};

export type TagVendor = string;
export type TagPlatform = string;
export type TagKnowledgeType = string;

export type FileTags = {
  file_id: number;
  doc_type: string | null;
  intent: string | null;
  tags_topic: string[];
  vendor: TagVendor;
  platform: TagPlatform;
  knowledge_type: TagKnowledgeType;
  chunk_count: number;
};

export async function listFileTags(kbId: number): Promise<FileTags[]> {
  if (isMockDataMode()) return [];
  const res = await api.get<FileTags[]>(`/rag/kb/${kbId}/file-tags`);
  return res.data;
}

export async function updateFileTags(
  kbId: number,
  fileId: number,
  input: {
    vendor: TagVendor;
    platform: TagPlatform;
    knowledge_type: TagKnowledgeType;
  },
): Promise<FileTags> {
  const res = await api.patch<FileTags>(
    `/knowledge-bases/${kbId}/files/${fileId}/tags`,
    input,
    { timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS },
  );
  return res.data;
}

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const res = await api.get<KnowledgeBase[]>("/knowledge-bases");
  return res.data;
}

export async function createKnowledgeBase(input: {
  name: string;
  description?: string | null;
}): Promise<KnowledgeBaseCreated> {
  const res = await api.post<KnowledgeBaseCreated>("/knowledge-bases", {
    name: input.name,
    description: input.description ?? null,
  });
  return res.data;
}

export async function updateKnowledgeBase(
  id: number,
  input: { name?: string; description?: string | null },
): Promise<KnowledgeBaseCreated> {
  // Pass empty string to clear description; omit a field to leave it alone.
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.description !== undefined)
    body.description = input.description ?? "";
  const res = await api.patch<KnowledgeBaseCreated>(
    `/knowledge-bases/${id}`,
    body,
  );
  return res.data;
}

export async function deleteKnowledgeBase(id: number): Promise<void> {
  await api.delete(`/knowledge-bases/${id}`);
}

export async function listFiles(kbId: number): Promise<KnowledgeFile[]> {
  const res = await api.get<KnowledgeFile[]>(`/knowledge-bases/${kbId}/files`);
  return res.data;
}

export async function uploadFile(
  kbId: number,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<KnowledgeFile> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post<KnowledgeFile>(
    `/knowledge-bases/${kbId}/files`,
    form,
    {
      timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
      onUploadProgress: (e) => {
        if (!onProgress || !e.total) return;
        onProgress(Math.min(100, Math.round((e.loaded / e.total) * 100)));
      },
    },
  );
  return res.data;
}

export async function deleteFile(kbId: number, fileId: number): Promise<void> {
  await api.delete(`/knowledge-bases/${kbId}/files/${fileId}`);
}

export async function downloadKnowledgeFile(
  fileId: number,
  fallbackFilename: string,
): Promise<void> {
  if (isMockDataMode()) {
    downloadBlob(
      new Blob([`Mock source download for ${fallbackFilename}\n`], {
        type: "text/plain;charset=utf-8",
      }),
      safeFilename(fallbackFilename, `source-${fileId}.txt`),
    );
    return;
  }

  const res = await api.get<Blob>(`/knowledge-bases/files/${fileId}/download`, {
    responseType: "blob",
  });
  const filename =
    filenameFromContentDisposition(res.headers["content-disposition"]) ??
    safeFilename(fallbackFilename, `source-${fileId}`);
  downloadBlob(res.data, filename);
}

function filenameFromContentDisposition(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(value);
  if (utf8?.[1]) return safeFilename(decodeURIComponent(utf8[1]));
  const quoted = /filename="([^"]+)"/i.exec(value);
  if (quoted?.[1]) return safeFilename(quoted[1]);
  const bare = /filename=([^;]+)/i.exec(value);
  return bare?.[1] ? safeFilename(bare[1]) : null;
}
