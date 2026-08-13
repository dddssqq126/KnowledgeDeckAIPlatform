"use client";

import { isAxiosError } from "axios";
import { CheckCircle2, FileText, ImagePlus, Upload, XCircle } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";

import {
  uploadImageFile,
  uploadTextFile,
  type KnowledgeFile,
} from "../lib/knowledge-bases";

const ACCEPTED = new Set([
  "txt",
  "pdf",
  "cs",
  "md",
  "docx",
  "pptx",
  "py",
  "html",
  "css",
  "bas",
]);
const ACCEPT_ATTR = ".txt,.pdf,.cs,.md,.docx,.pptx,.py,.html,.css,.bas";
const IMAGE_ACCEPT_ATTR = ".pdf,.pptx";
const IMAGE_ACCEPTED = new Set(["pdf", "pptx"]);

const ERROR_FALLBACKS: Record<string, string> = {
  invalid_extension:
    "Only TXT, PDF, CS, MD, DOCX, PPTX, PY, HTML, CSS, and BAS are accepted",
  invalid_content: "File contents do not match the file type",
  file_too_large: "File exceeds the 50 MB limit",
  duplicate_filename: "A file with this name already exists",
  storage_error: "Storage failed",
  image_mode_requires_pdf_or_pptx: "Image extraction only supports PDF and PPTX",
};

type RowStatus = "queued" | "uploading" | "done" | "error" | "skipped";

type Row = {
  key: string;
  file: File;
  displayName: string;
  status: RowStatus;
  progress: number;
  error: string | null;
  upload: (
    kbId: number,
    file: File,
    onProgress?: (percent: number) => void,
  ) => Promise<KnowledgeFile>;
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

function buildRows(
  files: File[],
  upload: Row["upload"],
  accepted: ReadonlySet<string>,
): { rows: Row[]; skippedCount: number } {
  const rows: Row[] = [];
  let skippedCount = 0;

  for (const file of files) {
    const display =
      (file as any).__relativePath ?? (file as any).webkitRelativePath ?? file.name;
    if (
      !accepted.has(ext(file.name))
    ) {
      skippedCount++;
      continue;
    }
    rows.push({
      key: `${upload.name}:${display}:${file.size}:${file.lastModified}`,
      file,
      displayName: display,
      status: "queued",
      progress: 0,
      error: null,
      upload,
    });
  }

  return { rows, skippedCount };
}

export function DropUpload({ kbId, onAllUploaded }: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  const [skipped, setSkipped] = useState(0);
  const [running, setRunning] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);

  function addFiles(
    files: File[],
    upload: Row["upload"],
    accepted: ReadonlySet<string>,
  ) {
    const { rows: newRows, skippedCount } = buildRows(files, upload, accepted);
    setRows((current) => {
      const seen = new Set(current.map((row) => row.key));
      return [...current, ...newRows.filter((row) => !seen.has(row.key))];
    });
    if (skippedCount > 0) setSkipped((count) => count + skippedCount);
  }

  function onPickTextFiles(e: ChangeEvent<HTMLInputElement>) {
    if (!e.target.files) return;
    addFiles(Array.from(e.target.files), uploadTextFile, ACCEPTED);
    e.target.value = "";
  }

  function onPickImageFiles(e: ChangeEvent<HTMLInputElement>) {
    if (!e.target.files) return;
    addFiles(Array.from(e.target.files), uploadImageFile, IMAGE_ACCEPTED);
    e.target.value = "";
  }

  async function startUpload() {
    if (running) return;
    setRunning(true);

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      if (row.status === "done") continue;
      setRows((current) =>
        current.map((item, index) =>
          index === i
            ? { ...item, status: "uploading", progress: 0, error: null }
            : item,
        ),
      );
      try {
        await row.upload(
          kbId,
          row.file,
          (percent) => {
            setRows((current) =>
              current.map((item, index) =>
                index === i ? { ...item, progress: percent } : item,
              ),
            );
          },
        );
        setRows((current) =>
          current.map((item, index) =>
            index === i ? { ...item, status: "done", progress: 100 } : item,
          ),
        );
      } catch (err) {
        setRows((current) =>
          current.map((item, index) =>
            index === i
              ? { ...item, status: "error", error: detailMessage(err) }
              : item,
          ),
        );
      }
    }

    setRunning(false);
    onAllUploaded();
  }

  function clearDone() {
    setRows((current) => current.filter((row) => row.status !== "done"));
    setSkipped(0);
  }

  const queuedCount = rows.filter((row) => row.status === "queued").length;
  const errorCount = rows.filter((row) => row.status === "error").length;
  const doneCount = rows.filter((row) => row.status === "done").length;

  return (
    <div className="space-y-2">
      <div className="rounded-md border border-border bg-muted/30 p-4 text-center">
        <div className="text-sm font-medium">Add knowledge</div>
        <div className="mt-1 text-xs text-muted-foreground">
          Upload text from a document, or upload images from a PDF / PPTX. Files
          are limited to 50 MB each.
        </div>
        <div className="mt-3 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 rounded-md bg-foreground px-4 py-2 text-xs font-medium text-white hover:opacity-90"
          >
            <FileText className="h-3.5 w-3.5" /> Upload text
          </button>
          <button
            type="button"
            onClick={() => imageInputRef.current?.click()}
            className="flex items-center gap-1.5 rounded-md border border-border bg-white px-4 py-2 text-xs font-medium hover:bg-muted"
          >
            <ImagePlus className="h-3.5 w-3.5" /> Upload images
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          onChange={onPickTextFiles}
          className="hidden"
        />
        <input
          ref={imageInputRef}
          type="file"
          multiple
          accept={IMAGE_ACCEPT_ATTR}
          onChange={onPickImageFiles}
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
              {rows.length} queued - {doneCount} done
              {errorCount > 0 ? ` - ${errorCount} failed` : ""}
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
                {running ? "Uploading..." : `Upload ${queuedCount + errorCount}`}
              </button>
            </div>
          </div>
          <ul className="divide-y divide-border">
            {rows.map((row) => (
              <li
                key={row.key}
                className="flex items-center gap-2 px-3 py-2 text-xs"
              >
                <RowIcon status={row.status} />
                <div className="min-w-0 flex-1">
                  <div className="truncate" title={row.displayName}>
                    {row.displayName}
                  </div>
                  {row.status === "uploading" ? (
                    <div className="mt-1 h-1 w-full rounded-full bg-muted">
                      <div
                        className="h-1 rounded-full bg-foreground transition-all"
                        style={{ width: `${row.progress}%` }}
                      />
                    </div>
                  ) : null}
                  {row.error ? (
                    <div className="mt-0.5 text-red-600">{row.error}</div>
                  ) : null}
                </div>
                <div className="text-muted-foreground">
                  {(row.file.size / 1024).toFixed(1)} KB
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
  if (status === "done")
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />;
  if (status === "error")
    return <XCircle className="h-3.5 w-3.5 text-red-600" />;
  if (status === "uploading")
    return <Upload className="h-3.5 w-3.5 animate-pulse text-foreground" />;
  return <Upload className="h-3.5 w-3.5 text-muted-foreground" />;
}
