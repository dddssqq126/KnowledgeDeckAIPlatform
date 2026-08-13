"use client";

import { isAxiosError } from "axios";
import { ArrowDown, ArrowUp, Pencil, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { DropUpload } from "../../../../components/DropUpload";
import { useKbStore } from "../../../../lib/kb-store";
import {
  type KnowledgeFile,
  deleteFile,
  listFiles,
} from "../../../../lib/knowledge-bases";

function detailMessage(err: unknown, fallbackMap: Record<string, string>): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return fallbackMap[detail] ?? detail;
  }
  return err instanceof Error ? err.message : "Unexpected error";
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

type SortKey = "uploaded" | "size" | "extension";
type SortDir = "asc" | "desc";

function sortFiles(
  files: KnowledgeFile[],
  key: SortKey,
  dir: SortDir,
): KnowledgeFile[] {
  const sorted = [...files].sort((a, b) => {
    switch (key) {
      case "size":
        return a.size_bytes - b.size_bytes;
      case "extension":
        return a.extension.localeCompare(b.extension) || a.filename.localeCompare(b.filename);
      case "uploaded":
      default:
        return a.created_at.localeCompare(b.created_at);
    }
  });
  return dir === "desc" ? sorted.reverse() : sorted;
}

const STATUS_LABEL: Record<string, string> = {
  uploaded: "Pending processing",
  parsing: "Parsing…",
  parsed: "Parsed",
  embedding: "Embedding…",
  indexed: "Indexed",
  failed: "Failed",
};

export default function KnowledgeBaseDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const kbId = Number(params.id);

  const kbs = useKbStore((s) => s.kbs);
  const loadedKbs = useKbStore((s) => s.loaded);
  const refreshKbs = useKbStore((s) => s.refresh);
  const setFileCount = useKbStore((s) => s.setFileCount);
  const removeKb = useKbStore((s) => s.remove);
  const renameKb = useKbStore((s) => s.rename);

  const kb = kbs.find((k) => k.id === kbId);

  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("uploaded");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const sortedFiles = useMemo(
    () => sortFiles(files, sortKey, sortDir),
    [files, sortKey, sortDir],
  );

  function flipSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(nextKey);
      // Sensible defaults: newest first for time, biggest first for size,
      // alphabetical for type.
      setSortDir(nextKey === "extension" ? "asc" : "desc");
    }
  }

  // Make sure the store is hydrated so we can resolve the KB by id even if
  // the user landed directly on this URL.
  useEffect(() => {
    if (!loadedKbs) refreshKbs();
  }, [loadedKbs, refreshKbs]);

  async function refreshFiles() {
    setLoadingFiles(true);
    try {
      const list = await listFiles(kbId);
      setFiles(list);
      setFileCount(kbId, list.length);
    } finally {
      setLoadingFiles(false);
    }
  }

  useEffect(() => {
    if (!Number.isFinite(kbId)) return;
    refreshFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbId]);

  async function handleDeleteFile(file: KnowledgeFile) {
    if (!window.confirm(`Delete "${file.filename}"?`)) return;
    await deleteFile(kbId, file.id);
    await refreshFiles();
  }

  async function handleDeleteKb() {
    if (!kb) return;
    if (!window.confirm(`Delete "${kb.name}" and all its files?`)) return;
    await removeKb(kb.id);
    router.push("/knowledge-bases");
  }

  async function handleRename(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!kb) return;
    const trimmed = draftName.trim();
    if (!trimmed) return;
    setSaving(true);
    setRenameError(null);
    try {
      await renameKb(kb.id, trimmed);
      setEditing(false);
    } catch (err) {
      setRenameError(
        detailMessage(err, {
          duplicate_kb_name: "A knowledge base with this name already exists",
        }),
      );
    } finally {
      setSaving(false);
    }
  }

  if (loadedKbs && !kb) {
    return (
      <section className="h-full overflow-auto px-6 py-6">
        <div className="mx-auto max-w-3xl">
          <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-sm text-muted-foreground">
            Knowledge base not found.
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="h-full overflow-auto px-6 py-6">
      <div className="mx-auto max-w-3xl space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {editing ? (
              <form onSubmit={handleRename} className="space-y-2">
                <input
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  maxLength={100}
                  autoFocus
                  className="w-full rounded-md border border-border bg-white px-3 py-2 text-base"
                />
                {renameError ? (
                  <div className="text-xs text-red-600">{renameError}</div>
                ) : null}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    className="rounded-md border border-border bg-white px-3 py-1 text-xs hover:bg-muted"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={saving || !draftName.trim()}
                    className="rounded-md bg-foreground px-3 py-1 text-xs text-white disabled:opacity-50"
                  >
                    {saving ? "..." : "Save"}
                  </button>
                </div>
              </form>
            ) : (
              <>
                <h1 className="truncate text-xl font-semibold">
                  {kb?.name ?? "Loading…"}
                </h1>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {kb ? (
                    <span>Created {formatTimestamp(kb.created_at)}</span>
                  ) : null}
                  {kb?.description ? (
                    <>
                      <span aria-hidden>·</span>
                      <span>{kb.description}</span>
                    </>
                  ) : null}
                </div>
              </>
            )}
          </div>
          {!editing && kb ? (
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setDraftName(kb.name);
                  setRenameError(null);
                  setEditing(true);
                }}
                aria-label="Rename"
                className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={handleDeleteKb}
                aria-label="Delete"
                className="rounded-md border border-border px-2 py-1 text-xs text-red-600 hover:bg-red-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null}
        </div>

        {kb ? <DropUpload kbId={kb.id} onAllUploaded={refreshFiles} /> : null}

        {loadingFiles ? (
          <div className="text-xs text-muted-foreground">Loading files…</div>
        ) : files.length === 0 ? (
          <div className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
            No files yet.
          </div>
        ) : (
          <div className="rounded-md border border-border bg-white">
            <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs text-muted-foreground">
              <span>
                {files.length} {files.length === 1 ? "file" : "files"}
              </span>
              <div className="flex items-center gap-1">
                <span>Sort:</span>
                <SortButton
                  label="Uploaded"
                  active={sortKey === "uploaded"}
                  dir={sortDir}
                  onClick={() => flipSort("uploaded")}
                />
                <SortButton
                  label="Size"
                  active={sortKey === "size"}
                  dir={sortDir}
                  onClick={() => flipSort("size")}
                />
                <SortButton
                  label="Type"
                  active={sortKey === "extension"}
                  dir={sortDir}
                  onClick={() => flipSort("extension")}
                />
              </div>
            </div>
            <ul className="divide-y divide-border">
              {sortedFiles.map((f) => (
                <li
                  key={f.id}
                  className="flex items-center justify-between px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm">{f.filename}</div>
                    <div className="text-xs text-muted-foreground">
                      {f.extension.toUpperCase()} · {humanSize(f.size_bytes)} ·{" "}
                      <StatusBadge status={f.status} error={f.status_error} /> ·
                      {" "}
                      Uploaded {formatTimestamp(f.created_at)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteFile(f)}
                    aria-label={`Delete ${f.filename}`}
                    className="ml-2 rounded-md border border-border px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

function StatusBadge({ status, error }: { status: string; error: string | null }) {
  const tone =
    status === "indexed"
      ? "text-emerald-600"
      : status === "failed"
        ? "text-red-600"
        : "text-muted-foreground";
  return (
    <span className={tone} title={error ?? ""}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function SortButton({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-0.5 rounded px-2 py-0.5 ${
        active
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      {label}
      {active ? (
        dir === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : null}
    </button>
  );
}
