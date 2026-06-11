"use client";

import { isAxiosError } from "axios";
import { CheckCircle2, FolderUp, Upload, XCircle } from "lucide-react";
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { uploadFile } from "../lib/knowledge-bases";

const ACCEPTED = new Set([
  "txt", "pdf", "cs", "md", "docx", "pptx", "xlsx", "csv",
  "py", "html", "css",
]);

const ERROR_FALLBACKS: Record<string, string> = {
  invalid_extension:
    "Only TXT, PDF, CS, MD, DOCX, PPTX, XLSX, CSV, PY, HTML, and CSS are accepted",
  invalid_content: "File contents do not match the file type",
  file_too_large: "File exceeds the 50 MB limit",
  duplicate_filename: "A file with this name already exists",
  storage_error: "Storage failed",
};

type RowStatus = "queued" | "uploading" | "done" | "error" | "skipped";

type Row = {
  key: string;
  file: File;
  // Display path (from webkitRelativePath when available, else just file.name)
  displayName: string;
  status: RowStatus;
  progress: number;
  error: string | null;
};

type Props = {
  kbId: number;
  onAllUploaded: () => void;
};

function detailMessage(err: unknown): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return ERROR_FALLBACKS[detail] ?? detail;
  }
  return err instanceof Error ? err.message : "Failed";
}

function ext(name: string): string {
  return name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
}

/**
 * Walks a DataTransferItem (which may be a directory) and yields all File
 * objects under it. Uses the non-standard but widely-supported
 * webkitGetAsEntry / readEntries API.
 */
async function filesFromDataTransfer(items: DataTransferItemList): Promise<File[]> {
  const out: File[] = [];

  async function walkEntry(entry: any, path: string): Promise<void> {
    if (entry.isFile) {
      await new Promise<void>((resolve) => {
        entry.file((file: File) => {
          // Stash the relative path so we can show it in the row.
          // (File doesn't allow setting webkitRelativePath, so wrap.)
          (file as any).__relativePath = path + file.name;
          out.push(file);
          resolve();
        });
      });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const all: any[] = [];
      // readEntries returns at most ~100 entries per call; loop until empty.
      while (true) {
        const batch: any[] = await new Promise((resolve) =>
          reader.readEntries((e: any[]) => resolve(e)),
        );
        if (batch.length === 0) break;
        all.push(...batch);
      }
      for (const child of all) {
        await walkEntry(child, path + entry.name + "/");
      }
    }
  }

  const tasks: Promise<void>[] = [];
  for (let i = 0; i < items.length; i++) {
    const entry = (items[i] as any).webkitGetAsEntry?.();
    if (entry) tasks.push(walkEntry(entry, ""));
    else {
      const f = items[i].getAsFile();
      if (f) out.push(f);
    }
  }
  await Promise.all(tasks);
  return out;
}

function buildRows(files: File[]): { rows: Row[]; skippedCount: number } {
  const rows: Row[] = [];
  let skippedCount = 0;
  for (const f of files) {
    const display = (f as any).__relativePath ?? (f as any).webkitRelativePath ?? f.name;
    if (!ACCEPTED.has(ext(f.name))) {
      skippedCount++;
      continue;
    }
    rows.push({
      key: `${display}:${f.size}:${f.lastModified}`,
      file: f,
      displayName: display,
      status: "queued",
      progress: 0,
      error: null,
    });
  }
  return { rows, skippedCount };
}

export function DropUpload({ kbId, onAllUploaded }: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [skipped, setSkipped] = useState(0);
  const [running, setRunning] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  // Apply webkitdirectory at runtime — React types reject the camelCase
  // attribute on the JSX element, so set it directly on the DOM node.
  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute("webkitdirectory", "");
      folderInputRef.current.setAttribute("directory", "");
    }
  }, []);

  function addFiles(files: File[]) {
    const { rows: newRows, skippedCount } = buildRows(files);
    setRows((cur) => {
      const seen = new Set(cur.map((r) => r.key));
      return [...cur, ...newRows.filter((r) => !seen.has(r.key))];
    });
    if (skippedCount > 0) {
      setSkipped((c) => c + skippedCount);
    }
  }

  function onPickFiles(e: ChangeEvent<HTMLInputElement>) {
    if (!e.target.files) return;
    addFiles(Array.from(e.target.files));
    // Reset so re-selecting the same file fires onChange again.
    e.target.value = "";
  }

  async function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    if (!e.dataTransfer) return;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      const files = await filesFromDataTransfer(e.dataTransfer.items);
      addFiles(files);
    } else if (e.dataTransfer.files) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  }

  async function startUpload() {
    if (running) return;
    setRunning(true);
    // Sequential — backend is single-flight per request anyway, and this
    // gives the user a clear running-row indicator.
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.status === "done") continue;
      setRows((cur) =>
        cur.map((x, idx) =>
          idx === i ? { ...x, status: "uploading", progress: 0, error: null } : x,
        ),
      );
      try {
        await uploadFile(kbId, r.file, (pct) => {
          setRows((cur) =>
            cur.map((x, idx) => (idx === i ? { ...x, progress: pct } : x)),
          );
        });
        setRows((cur) =>
          cur.map((x, idx) =>
            idx === i ? { ...x, status: "done", progress: 100 } : x,
          ),
        );
      } catch (err) {
        setRows((cur) =>
          cur.map((x, idx) =>
            idx === i
              ? { ...x, status: "error", error: detailMessage(err) }
              : x,
          ),
        );
      }
    }
    setRunning(false);
    onAllUploaded();
  }

  function clearDone() {
    setRows((cur) => cur.filter((r) => r.status !== "done"));
    setSkipped(0);
  }

  const queuedCount = rows.filter((r) => r.status === "queued").length;
  const errorCount = rows.filter((r) => r.status === "error").length;
  const doneCount = rows.filter((r) => r.status === "done").length;

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={`rounded-md border-2 border-dashed p-4 text-center transition-colors ${
          isDragging
            ? "border-foreground bg-muted"
            : "border-border bg-muted/30"
        }`}
      >
        <div className="text-sm text-muted-foreground">
          Drop files or folders here
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          TXT / PDF / CS · up to 50 MB each · folders are walked recursively, other formats are skipped
        </div>
        <div className="mt-3 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1 rounded-md border border-border bg-white px-3 py-1.5 text-xs hover:bg-muted"
          >
            <Upload className="h-3.5 w-3.5" /> Choose files
          </button>
          <button
            type="button"
            onClick={() => folderInputRef.current?.click()}
            className="flex items-center gap-1 rounded-md border border-border bg-white px-3 py-1.5 text-xs hover:bg-muted"
          >
            <FolderUp className="h-3.5 w-3.5" /> Choose folder
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".txt,.pdf,.cs,.md,.docx,.pptx,.xlsx,.csv,.py,.html,.css"
          onChange={onPickFiles}
          className="hidden"
        />
        <input
          ref={folderInputRef}
          type="file"
          multiple
          onChange={onPickFiles}
          className="hidden"
        />
      </div>

      {skipped > 0 ? (
        <div className="text-xs text-amber-600">
          {skipped} file{skipped === 1 ? "" : "s"} skipped (unsupported format).
        </div>
      ) : null}

      {rows.length > 0 ? (
        <div className="rounded-md border border-border bg-white">
          <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs text-muted-foreground">
            <span>
              {rows.length} queued · {doneCount} done
              {errorCount > 0 ? ` · ${errorCount} failed` : ""}
            </span>
            <div className="flex gap-2">
              {doneCount > 0 ? (
                <button
                  type="button"
                  onClick={clearDone}
                  className="rounded border border-border px-2 py-0.5 text-xs hover:bg-muted"
                >
                  Clear done
                </button>
              ) : null}
              <button
                type="button"
                onClick={startUpload}
                disabled={running || queuedCount + errorCount === 0}
                className="rounded bg-foreground px-3 py-0.5 text-xs text-white disabled:opacity-50"
              >
                {running ? "Uploading…" : `Upload ${queuedCount + errorCount}`}
              </button>
            </div>
          </div>
          <ul className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.key} className="flex items-center gap-2 px-3 py-2 text-xs">
                <RowIcon status={r.status} />
                <div className="min-w-0 flex-1">
                  <div className="truncate" title={r.displayName}>
                    {r.displayName}
                  </div>
                  {r.status === "uploading" ? (
                    <div className="mt-1 h-1 w-full rounded-full bg-muted">
                      <div
                        className="h-1 rounded-full bg-foreground transition-all"
                        style={{ width: `${r.progress}%` }}
                      />
                    </div>
                  ) : null}
                  {r.error ? (
                    <div className="mt-0.5 text-red-600">{r.error}</div>
                  ) : null}
                </div>
                <div className="text-muted-foreground">
                  {(r.file.size / 1024).toFixed(1)} KB
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function RowIcon({ status }: { status: RowStatus }) {
  if (status === "done") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />;
  if (status === "error") return <XCircle className="h-3.5 w-3.5 text-red-600" />;
  if (status === "uploading") return <Upload className="h-3.5 w-3.5 animate-pulse text-foreground" />;
  return <Upload className="h-3.5 w-3.5 text-muted-foreground" />;
}
