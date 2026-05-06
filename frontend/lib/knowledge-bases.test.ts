import type { AxiosProgressEvent } from "axios";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { downloadBlob } from "./download";
import {
  createKnowledgeBase,
  deleteFile,
  deleteKnowledgeBase,
  downloadKnowledgeFile,
  listFiles,
  listKnowledgeBases,
  uploadFile,
} from "./knowledge-bases";

vi.mock("./download", () => ({
  downloadBlob: vi.fn(),
  safeFilename: (value: string, fallback = "download") => value || fallback,
}));

describe("knowledge-bases API client", () => {
  let mock: MockAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    mock = new MockAdapter(api);
  });

  afterEach(() => {
    mock.restore();
  });

  it("listKnowledgeBases hits GET /knowledge-bases", async () => {
    mock.onGet("/knowledge-bases").reply(200, [
      { id: 1, name: "A", description: null, file_count: 0, created_at: "t" },
    ]);
    const out = await listKnowledgeBases();
    expect(out).toHaveLength(1);
    expect(out[0]).toEqual({
      id: 1, name: "A", description: null, file_count: 0, created_at: "t",
    });
  });

  it("createKnowledgeBase POSTs name + description", async () => {
    mock.onPost("/knowledge-bases").reply((config) => {
      expect(JSON.parse(config.data)).toEqual({ name: "New", description: "d" });
      return [201, { id: 2, name: "New", description: "d", created_at: "t" }];
    });
    const out = await createKnowledgeBase({ name: "New", description: "d" });
    expect(out.id).toBe(2);
  });

  it("deleteKnowledgeBase hits DELETE /knowledge-bases/:id", async () => {
    mock.onDelete("/knowledge-bases/5").reply(204);
    await deleteKnowledgeBase(5);
  });

  it("listFiles hits GET /knowledge-bases/:id/files", async () => {
    mock.onGet("/knowledge-bases/3/files").reply(200, []);
    const out = await listFiles(3);
    expect(out).toEqual([]);
  });

  it("uploadFile sends multipart with file field", async () => {
    mock.onPost("/knowledge-bases/3/files").reply((config) => {
      expect(config.data).toBeInstanceOf(FormData);
      expect(config.data.get("file")).toBeInstanceOf(File);
      return [201, {
        id: 9, knowledge_base_id: 3, filename: "x.txt", extension: "txt",
        size_bytes: 1, status: "uploaded", status_error: null, created_at: "t",
      }];
    });
    const f = new File(["x"], "x.txt", { type: "text/plain" });
    const out = await uploadFile(3, f);
    expect(out.id).toBe(9);
  });

  it("uploadFile invokes onProgress with percentages", async () => {
    let lastPct = -1;
    mock.onPost("/knowledge-bases/3/files").reply((config) => {
      // Simulate axios progress event firing.
      config.onUploadProgress?.({ loaded: 50, total: 100 } as unknown as AxiosProgressEvent);
      config.onUploadProgress?.({ loaded: 100, total: 100 } as unknown as AxiosProgressEvent);
      return [201, {
        id: 9, knowledge_base_id: 3, filename: "x.txt", extension: "txt",
        size_bytes: 1, status: "uploaded", status_error: null, created_at: "t",
      }];
    });
    await uploadFile(3, new File(["x"], "x.txt"), (pct) => { lastPct = pct; });
    expect(lastPct).toBe(100);
  });

  it("deleteFile hits DELETE /knowledge-bases/:kb/files/:file", async () => {
    mock.onDelete("/knowledge-bases/3/files/9").reply(204);
    await deleteFile(3, 9);
  });

  it("downloadKnowledgeFile downloads the file returned by the backend", async () => {
    const blob = new Blob(["hello"], { type: "text/plain" });
    mock.onGet("/knowledge-bases/files/9/download").reply((config) => {
      expect(config.responseType).toBe("blob");
      return [
        200,
        blob,
        { "content-disposition": 'attachment; filename="server-name.txt"' },
      ];
    });

    await downloadKnowledgeFile(9, "fallback.txt");

    expect(downloadBlob).toHaveBeenCalledWith(blob, "server-name.txt");
  });

  it("uploadFile does not invoke onProgress when e.total is 0", async () => {
    let called = false;
    mock.onPost("/knowledge-bases/3/files").reply((config) => {
      config.onUploadProgress?.(
        { loaded: 0, total: 0 } as unknown as AxiosProgressEvent
      );
      return [201, {
        id: 9, knowledge_base_id: 3, filename: "x.txt", extension: "txt",
        size_bytes: 1, status: "uploaded", status_error: null, created_at: "t",
      }];
    });
    await uploadFile(3, new File(["x"], "x.txt"), () => { called = true; });
    expect(called).toBe(false);
  });
});
